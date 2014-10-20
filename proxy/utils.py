# coding=utf-8
import os
import re

__author__ = 'alex'


def get_absolute_url():
    """ retorna a url do site
    Ex: http(s)://localhost:8000
    """
    url_scheme = os.environ.get('wsgi.url_scheme', 'http')
    http_host = os.environ.get('HTTP_HOST', '')
    server_name = os.environ.get('SERVER_NAME', 'localhost')
    server_port = os.environ.get('SERVER_PORT', '8000')

    url = url_scheme + '://'

    if http_host:
        url += http_host
    else:
        url += server_name

    if url_scheme == 'https':
        if server_port != '443':
            url += ':' + server_port

    elif server_port != '80':
        url += ':' + server_port
    return url


def get_request_absolute_url(request):
    server_name = request.META['SERVER_NAME']
    request_uri = request.META['REQUEST_URI']
    scheme = request.META['wsgi.url_scheme']
    return "{scheme}://{server}{uri}".format(scheme=scheme, uri=request_uri,
                                             server=server_name)


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