import StringIO
from contextlib import closing
import tempfile
import urllib
from django.http import HttpResponse, StreamingHttpResponse
from django.core.cache import get_cache, DEFAULT_CACHE_ALIAS
import re
import requests
from proxy import utils
import time
import hashlib

__author__ = 'alex'


class Iterator(object):

    def __init__(self, data):
        self.data = data

    def __iter__(self):
        counter = 1024
        while True:
            before = time.time()
            chunk = self.data.read(counter)
            if not chunk and counter:
                break
            after = time.time()
            counter = self.best_block_size((after-before), len(chunk))
            yield chunk
        raise StopIteration

    @staticmethod
    def best_block_size(elapsed_time, bytes):
        new_min = max(bytes / 2.0, 1.0)
        new_max = min(max(bytes * 2.0, 1.0), 4194304) # Do not surpass 4 MB
        if elapsed_time < 0.001:
            return long(new_max)
        rate = bytes / elapsed_time
        if rate > new_max:
            return long(new_max)
        if rate < new_min:
            return long(new_min)
        return long(rate)


class Cache(object):
    sep = ':'

    def __init__(self, scope):
        self.scope = hashlib.md5(utils.ascii(scope)).hexdigest()
        self.cache = get_cache(DEFAULT_CACHE_ALIAS)

    def join(self, name):
        return self.sep.join([self.scope, name])

    def __getitem__(self, key):
        return self.cache.get(self.join(key))

    def __setitem__(self, key, value):
        self.cache.add(self.join(key), value)

    def has(self, name):
        return self.cache.has_key(self.join(name))

    def iter(self, name):
        content = self.cache.get(self.join(name))
        return Iterator(StringIO.StringIO(content))


class IterCaching(Iterator, Cache):
    def __init__(self, scope, data, **kwargs):
        Iterator.__init__(self, data)
        Cache.__init__(self, scope)
        self.temp = tempfile.TemporaryFile()
        self.kwargs = kwargs

    def __iter__(self):
        try:
            iterator = super(IterCaching, self).__iter__()
            for data in iterator:
                self.temp.write(data)
                yield data
        except StopIteration:
            raise
        finally:
            self.temp.seek(0)
            self[ProxyRequest.HEADERS] = self.kwargs
            self[ProxyRequest.CONTENT] = self.temp.read()
            self.temp.close()


class SmartCache(object):
    MEGABYTE = 1024 ** 2

    pattern_app = re.compile("^application/(?:octet-stream.*?|x-shockwave.*?)")
    pattern_video = re.compile("^video/.*")

    def __init__(self, **headers):
        self.headers = headers

    @property
    def content_type(self):
        return self.headers.get('content-type', '')

    @property
    def transfer_encoding(self):
        return self.headers.get('transfer-encoding', '')

    @property
    def is_image(self):
        return self.content_type.startswith('image')

    @property
    def is_chunked(self):
        return self.transfer_encoding == 'chucked'

    @property
    def is_application(self):
        return bool(self.pattern_app.match(self.content_type))

    @property
    def is_video(self):
        return bool(self.pattern_video.match(self.content_type))

    def is_iterable(self):
        return self.is_image or self.is_chunked or self.is_application or self.is_video

    def is_cacheable(self):
        return self.is_image


class ProxyRequest(object):
    """ proxy server it self """
    CONTENT = 'text'
    HEADERS = 'headers'

    NO_PROXY = {'no': 'pass'}

    HOP_BY_HOP_HEADER = [
        'connection',
        'keep-alive',
        'proxy-authenticate',
        'proxy-authorization',
        'te',
        'trailers',
        'transfer-encoding',
        'upgrade',
        'content-encoding',
    ]

    REQUEST_HEADERS = [
        'USER-AGENT',
        'ACCEPT-ENCODING',
        'ACCEPT-LANGUAGE',
        'CONTENT-TYPE',
        'COOKIE'
    ]

    @staticmethod
    def get_path(request):
        path = request.path.lstrip('/').strip()
        if not path or not path.startswith('http'):
            path = utils.get_request_absolute_url(request)
        if request.method == 'GET' and request.META['QUERY_STRING']:
            path += ('?' + request.META['QUERY_STRING'])
            path = urllib.unquote_plus(str(path))
        return path

    def process_request(self, request):
        path = self.get_path(request)
        cache = Cache(path)

        if cache.has(self.CONTENT) and cache.has(self.HEADERS):
            response = self._response_cache(request, cache)
        else:
            response = self._response_web(request, cache)

        return response

    def _response_cache(self, request, cache):
        _smart = SmartCache(**cache[self.HEADERS])
        if _smart.is_iterable():
            response = StreamingHttpResponse(cache.iter(self.CONTENT))
        else:
            response = HttpResponse(cache[self.CONTENT])
        for header, value in cache[self.HEADERS].iteritems():
            response[header] = value
        return response

    def _response_web(self, request, cache):
        session = requests.Session()
        session.trust_env = False

        request_headers = utils.get_request_headers(request)
        headers = utils.filter_by(request_headers, *self.REQUEST_HEADERS)

        path = self.get_path(request)

        with closing(session.request(request.method, path, proxies=self.NO_PROXY,
                                     data=request.POST.copy(), stream=True, headers=headers,
                                     allow_redirects=True)) as req:
            _smart = SmartCache(**req.headers)
            if _smart.is_iterable():
                if _smart.is_cacheable():
                    response = StreamingHttpResponse(IterCaching(path, req.raw))
                else:
                    response = StreamingHttpResponse(Iterator(req.raw))
                headers = self.copy_headers_to(req.headers, response)
                cache[self.HEADERS] = headers
                return response

            text = req.text

            response = HttpResponse(text)
            headers = self.copy_headers_to(req.headers, response)

            cache[self.HEADERS] = headers
            cache[self.CONTENT] = text

        return response

    @classmethod
    def copy_headers_to(cls, headers, response):
        _headers = {}
        for header, value in headers.iteritems():
            if not header.lower() in cls.HOP_BY_HOP_HEADER:
                response[header] = value
                _headers[header] = value
        return _headers