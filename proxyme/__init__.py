import wsgiref.util

# hack
wsgiref.util._hoppish = {
    'connection': 1, 'keep-alive': 1, 'proxy-authenticate': 1,
    'proxy-authorization': 1, 'te': 1, 'trailers': 1,
    'upgrade': 1
}.__contains__