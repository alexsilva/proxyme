from contextlib import closing
import re

from django.core.cache import get_cache, DEFAULT_CACHE_ALIAS
from django.http import HttpResponse, StreamingHttpResponse
import requests

from proxy import utils
from proxy.cache.backend import Iterator


__author__ = 'alex'


class SmartCache(object):
    pattern_program = re.compile("^(?:application/(?:octet-stream.*?|x-shockwave.*?)|font.*$)")
    pattern_text = re.compile("^(?:text/.*$|application/(?:(?:x-)?javascript|xhtml.*$|vnd.*$))", re.I)
    pattern_media = re.compile("^(?:video/.*$|audio/.*$)")

    def __init__(self, cache, **headers):
        self.cache = cache
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
    def is_fileobj(self):
        return self.headers.get(self.cache.STREAM_KEY, False)

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

    @staticmethod
    def make_scope_key(request):
        return "{0!s}:{1!s}".format(request.method, utils.get_path(request=request))

    def process_request(self, request):
        cache = get_cache(DEFAULT_CACHE_ALIAS, scope=self.make_scope_key(request))

        if cache.has_key(cache.META_KEY) and cache.has_key(cache.CONTENT_KEY):
            # noinspection PyBroadException
            try:
                response = self._response_cache(request, cache)
            except Exception as e:
                response = self._response_web(request, cache)
                print(e)
        else:
            response = self._response_web(request, cache)

        return response

    def _response_cache(self, request, cache):
        headers = cache[cache.META_KEY]

        _smart = SmartCache(cache, **headers)

        if _smart.is_text:
            response = HttpResponse(cache[cache.CONTENT_KEY])

        elif _smart.is_fileobj:
            response = StreamingHttpResponse(cache.iter_fileobj(cache.CONTENT_KEY))
        else:
            response = StreamingHttpResponse(cache.iter(cache.CONTENT_KEY))

        for header, value in headers.iteritems():
            response[header] = value

        self.setup_response_headers(response, headers)
        return response

    def _response_web(self, request, cache):
        session = requests.Session()
        session.trust_env = False

        _headers = utils.get_request_headers(request)
        request_headers = utils.exclude_by(_headers, *self.REQUEST_EXCLUDES)

        path = utils.get_path(request=request)

        with closing(session.request(request.method, path, proxies=self.NO_PROXY,
                                     data=request.POST.copy(), stream=True, headers=request_headers,
                                     allow_redirects=True)) as req:

            response_headers = req.headers

            _smart = SmartCache(cache, **response_headers)

            if _smart.is_text:
                req.raw.decode_content = True
                text = req.raw.read()

                response_headers = utils.exclude_by(req.headers, *self.RESPONSE_EXCLUDES)

                response = HttpResponse(text)
                cache[cache.CONTENT_KEY] = text

            elif _smart.is_cacheable():
                response = StreamingHttpResponse(cache.iter_set_stream(req.raw))
                request_headers[cache.STREAM_KEY] = True
            else:
                response = StreamingHttpResponse(Iterator(req.raw))

            headers = self.copy_headers(response_headers, response)
            headers[cache.STREAM_KEY] = request_headers.get(cache.STREAM_KEY, False)
            headers['REFERER'] = request_headers.get('REFERER', None)

            cache[cache.META_KEY] = headers

            self.setup_response_headers(response, request_headers)
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