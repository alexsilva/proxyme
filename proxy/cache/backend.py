import StringIO
import hashlib
import io
import os
import pickle
import tempfile
import time
import errno
import zlib

from django.core.cache.backends import filebased
import shutil

from proxy import utils


__author__ = 'alex'


class Iterator(object):
    def __init__(self, data):
        self.data = data

    def set_data(self, data):
        self.data = data

    def __iter__(self):
        counter = 1024
        while True:
            before = time.time()
            chunk = self.data.read(counter)
            if not chunk and counter:
                break
            after = time.time()
            counter = self.best_block_size((after - before), len(chunk))
            yield chunk
        raise StopIteration

    @staticmethod
    def best_block_size(elapsed_time, bytes):
        new_min = max(bytes / 2.0, 1.0)
        new_max = min(max(bytes * 2.0, 1.0), 4194304)  # Do not surpass 4 MB
        if elapsed_time < 0.001:
            return long(new_max)
        rate = bytes / elapsed_time
        if rate > new_max:
            return long(new_max)
        if rate < new_min:
            return long(new_min)
        return long(rate)


class FileBasedCache(filebased.FileBasedCache, Iterator):
    content_dir = 'djfiles'

    META_KEY = 'meta'
    CONTENT_KEY = 'content'
    STREAM_KEY = 'stream'
    FILEPATH_KEY = 'path'

    sep = ':'

    def __init__(self, path, params):
        super(FileBasedCache, self).__init__(path, params)
        self.scope = self.create_key(params.get('scope', ""))

        Iterator.__init__(self, None)

        self.stream_dir = os.path.join(self._dir, self.content_dir)

        if not os.path.exists(self.stream_dir):
            os.makedirs(self.stream_dir)

    def __call__(self, scope):
        self.scope = self.create_key(scope)

    @staticmethod
    def create_key(data):
        return hashlib.md5(utils.ascii(data)).hexdigest()

    def join(self, name):
        return self.sep.join([self.scope, name])

    def __getitem__(self, key):
        return self.get(self.join(key))

    def __setitem__(self, key, value):
        self.add(self.join(key), value)

    def has_key(self, key, version=None):
        return super(FileBasedCache, self).has_key(self.join(key), version=None)

    def iter(self, name):
        content = self.get(self.join(name))
        return Iterator(StringIO.StringIO(content))

    def iter_fileobj(self, name):
        return Iterator(open(self.get(self.join(name))[self.FILEPATH_KEY], 'rb'))

    def has_fileobj(self, name):
        return os.path.exists(self.get(self.join(name))[self.FILEPATH_KEY])

    @staticmethod
    def _remove_filepath(path):
        try:
            os.remove(path)
        except OSError as e:
            # ENOENT can happen if the cache file is removed (by another
            # process) after the os.path.exists check.
            if e.errno != errno.ENOENT:
                raise

    @staticmethod
    def get_content(fname, default=None):
        if os.path.exists(fname):
            try:
                with io.open(fname, 'rb') as f:
                    pickle.load(f)  # compat
                    return pickle.loads(zlib.decompress(f.read()))
            except IOError as e:
                if e.errno == errno.ENOENT:
                    pass  # Cache file was removed after the exists check
        return default

    def _delete(self, key):
        params = self.get_content(key, {})

        if type(params) is dict and params.get(self.STREAM_KEY, False) and self.FILEPATH_KEY in params:
            self._remove_filepath(params[self.FILEPATH_KEY])

        super(FileBasedCache, self)._delete(key)

    def clear(self):
        """ clear all cache content """
        super(FileBasedCache, self).clear()
        shutil.rmtree(self.stream_dir)

    def iter_set_stream(self, data, **kwargs):
        fileobj = tempfile.NamedTemporaryFile(dir=self.stream_dir, delete=False)
        self.set_data(data)  # stream set
        try:
            for data in super(FileBasedCache, self).__iter__():
                fileobj.write(data)
                yield data
        except StopIteration:
            raise
        finally:
            kwargs[self.STREAM_KEY] = True
            kwargs[self.FILEPATH_KEY] = fileobj.name

            self.add(self.join(self.CONTENT_KEY), kwargs)

            fileobj.close()