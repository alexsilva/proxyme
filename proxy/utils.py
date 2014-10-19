import os

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
