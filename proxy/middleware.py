import StringIO
import copy
from django.http import HttpResponse, StreamingHttpResponse
from django.core.cache import get_cache, DEFAULT_CACHE_ALIAS
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
            print chunk
            if not chunk:
                break
            after = time.time()
            counter = self.best_block_size((after-before), chunk)
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
        self.scope = hashlib.md5(scope).hexdigest()
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
        'content-encoding'
    ]

    def __init__(self):
        pass

    @staticmethod
    def get_path(request):
        path = request.path.lstrip('/').strip()
        if not path or not path.startswith('http'):
            path = utils.get_request_absolute_url(request)
        return path

    def process_request(self, request):
        cache = Cache(self.get_path(request))

        if cache.has(self.CONTENT) and cache.has(self.HEADERS):
            response = self._response_cache(request, cache)
        else:
            response = self._response_web(request, cache)

        return response

    def _response_cache(self, request, cache):
        stream = False
        for value in cache[self.HEADERS].itervalues():
            if value.startswith('image'):
                stream = True
                break
        if stream:
            response = StreamingHttpResponse(cache.iter(self.CONTENT))
        else:
            response = HttpResponse(cache[self.CONTENT])
        for header, value in cache[self.HEADERS].iteritems():
            response[header] = value
        return response

    def _response_web(self, request, cache):
        session = requests.Session()
        session.trust_env = False

        headers = copy.deepcopy(request.GET)
        headers.update(request.POST)

        req = session.request(request.method, self.get_path(request), proxies=self.NO_PROXY, headers=headers)

        if req.headers['content-type'].startswith('image'):
            req = session.request(request.method, self.get_path(request), proxies=self.NO_PROXY,
                                  stream=True)
            response = StreamingHttpResponse(req.raw)
            self.copy_headers_to(req.headers, response)
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