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

    pattern_program = re.compile("^(?:application/(?:octet-stream.*?|x-shockwave.*?)|font.*$)")
    pattern_text = re.compile("^(?:text/.*$|application/(?:(?:x-)?javascript|xhtml.*$|vnd.*$))", re.I)
    pattern_media = re.compile("^(?:video/.*$|audio/.*$)")

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
        return self.transfer_encoding == 'chunked'

    @property
    def is_application(self):
        return bool(self.pattern_program.match(self.content_type))

    @property
    def is_media(self):
        return bool(self.pattern_media.match(self.content_type))

    @property
    def is_text(self):
        return bool(self.pattern_text.match(self.content_type) or not self.content_type)

    def is_iterable(self):
        return self.is_image or self.is_chunked or self.is_application or self.is_media

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

    REQUEST_EXCLUDES = [
        'CONTENT-LENGTH',
        'IF-MODIFIED-SINCE',
        'IF-NONE-MATCH',
        'HOST'
    ]

    RESPONSE_EXCLUDES = [
        'content-length',
        'content-encoding'
    ]

    FRAME_OPTION = 'ALLOW-FROM {REFERER}'

    def process_request(self, request):
        cache = Cache("{0!s}:{1!s}".format(request.method, utils.get_path(request)))

        if cache.has(self.CONTENT) and cache.has(self.HEADERS):
            response = self._response_cache(request, cache)
        else:
            response = self._response_web(request, cache)

        return response

    def _response_cache(self, request, cache):
        headers = cache[self.HEADERS]

        _smart = SmartCache(**headers)

        if _smart.is_text:
            response = HttpResponse(cache[self.CONTENT])
        else:
            response = StreamingHttpResponse(cache.iter(self.CONTENT))
        for header, value in headers.iteritems():
            response[header] = value

        self.setup_response_headers(response, headers)
        return response

    def _response_web(self, request, cache):
        session = requests.Session()
        session.trust_env = False

        request_headers = utils.get_request_headers(request)
        req_headers = utils.exclude_by(request_headers, *self.REQUEST_EXCLUDES)

        path = utils.get_path(request)

        with closing(session.request(request.method, path, proxies=self.NO_PROXY,
                                     data=request.POST.copy(), stream=True, headers=req_headers,
                                     allow_redirects=True)) as req:

            resp_headers = req.headers

            _smart = SmartCache(**resp_headers)

            if _smart.is_text:
                req.raw.decode_content = True
                text = req.raw.read()

                resp_headers = utils.exclude_by(
                    req.headers, *self.RESPONSE_EXCLUDES)

                response = HttpResponse(text)
                cache[self.CONTENT] = text
            elif _smart.is_cacheable():
                response = StreamingHttpResponse(IterCaching(path, req.raw))
            else:
                response = StreamingHttpResponse(Iterator(req.raw))

            headers = self.copy_headers(resp_headers, response)
            headers['REFERER'] = req_headers.get('REFERER', None)
            cache[self.HEADERS] = headers

            self.setup_response_headers(response, req_headers)
        return response

    @classmethod
    def setup_response_headers(cls, response, headers):
        if bool(headers.get('REFERER', None)):
            response['X-Frame-Options'] = cls.FRAME_OPTION.format(
                **headers)

    @classmethod
    def copy_headers(cls, headers, response):
        _headers = {}
        for header, value in headers.iteritems():
            if not header.lower() in cls.HOP_BY_HOP_HEADER:
                response[header] = value
                _headers[header] = value
        return _headers