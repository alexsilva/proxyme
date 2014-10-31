# coding=utf-8
import re
from unicodedata import normalize

from django.utils import lru_cache


__author__ = 'alex'


def get_request_url(request):
    fmt = "{scheme}://{server}{uri}"

    server_name = request.META['SERVER_NAME']
    request_uri = request.META['REQUEST_URI']
    scheme = request.META['wsgi.url_scheme']

    return fmt.format(scheme=scheme, uri=request_uri,
                      server=server_name)


@lru_cache.lru_cache()
def get_path(**kwargs):
    request = kwargs.get('request')
    path = request.path.lstrip('/').strip()
    if not path or not path.startswith('http'):
        path = get_request_url(request)
    if request.method == 'GET' and request.META['QUERY_STRING']:
        path += ('?' + request.META['QUERY_STRING'])
    return str(path)


def get_request_headers(request):
    """ Dicionário com os headers http """
    regex_http_ = re.compile(r'^HTTP_.+$')
    regex_content_type = re.compile(r'^CONTENT_TYPE$')
    regex_content_length = re.compile(r'^CONTENT_LENGTH$')
    regex_http = re.compile('^HTTP_')

    headers = {}

    for header in request.META:
        if regex_http_.match(header) or regex_content_type.match(header) or \
                regex_content_length.match(header):
            name = regex_http.sub('', str(header))
            name = name.replace('_', '-')

            headers[name] = request.META[header]
    return headers


def filter_by(items, *options):
    _options = {}
    for h in options:
        if h in items:
            _options[h] = items[h]
    return _options


def exclude_by(items, *options):
    _options = {}
    for h in items:
        if not h in options:
            _options[h] = items[h]
    return _options


def ascii(txt):
    if isinstance(txt, unicode):
        txt = normalize('NFKD', txt).encode('ASCII', 'ignore')
    return txt