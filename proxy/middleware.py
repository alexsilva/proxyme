import StringIO
from contextlib import closing
import copy
import urllib
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

    @property
    def content(self):
        return ''.join(self)


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
        'content-encoding',
    ]

    REQUEST_HEADERS = [
        'USER-AGENT',
        'ACCEPT-ENCODING',
        'ACCEPT-LANGUAGE',
        'CONTENT-TYPE'
    ]

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

        data = request.GET.copy()
        data.update(request.POST)

        url = self.get_path(request)

        if request.method == 'GET':
            url += urllib.urlencode(data)
            data = None

        request_headers = utils.get_request_headers(request)
        headers = utils.filter_by(request_headers, *self.REQUEST_HEADERS)

        with closing(session.request(request.method, url, proxies=self.NO_PROXY,
                                     data=data, stream=True, headers=headers, allow_redirects=True)) as req:
            if req.headers.get('content-type', '').startswith('image'):
                response = StreamingHttpResponse(Iterator(req.raw))
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