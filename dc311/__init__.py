import httplib2
import urllib
import urlparse
try:
    import simplejson
except ImportError:
    from django.utils import simplejson

http = httplib2.Http()

class RequestError(Exception):
    """Raised if a request returns a non-200 response"""
    def __init__(self, message, url, headers, body, req_body=None):
        self.message = message
        self.url = url
        self.req_body = req_body
        self.headers = headers
        self.body = body
    def __str__(self):
        return '%s in request to %s: %s\n%s' % (
            self.message,
            self.url,
            self.headers['status'],
            self.body.strip())

class Service(object):
    """Represents the service to which you are connecting.

    By default this will connect to the public API (located at
    http://api.dc.gov/open311/v1/).  You may also provide your apikey
    (which you must sign up for), though many methods work without a
    key.

    If you want caching, you can use
    ``http=httplib2.Http('cache_dir')``.
    """

    default_base_url = 'http://api.dc.gov/open311/v1/'

    def __init__(self, base_url=default_base_url,
                 apikey=None, http=http):
        if not base_url.endswith('/'):
            base_url += '/'
        self.base_url = base_url
        self.apikey = apikey
        self.http = http

    def __repr__(self):
        args = []
        if self.base_url != self.default_base_url:
            args.append(' base_url=%s' % self.base_url)
        if self.apikey:
            args.append(' apikey=%s' % self.apikey)
        if self.http is not http:
            args.append(' http=%r' % self.http)
        return '<%s%s>' % (
            self.__class__.__name__, ''.join(args))

    def is_default(self):
        return (self.base_url == self.default_base_url
                and not self.apikey
                and self.http is http)
    
    def request(self, url, method='GET', **params):
        req_headers = {'Accept': 'application/json'}
        if self.apikey:
            params.setdefault('apikey', apikey)
        req_body = None
        if params and method == 'GET':
            if '?' in url:
                url += '&'
            else:
                url += '?'
            url += urllib.urlencode(sorted(params.iteritems()))
        elif params:
            req_body = urllib.urlencode(sorted(params.iteritems()))
        headers, body = self.http.request(url, method=method,
                                          body=req_body,
                                          headers=req_headers)
        status = int(headers['status'])
        if status != 200:
            raise RequestError('Error', url=url, headers=headers, body=body, req_body=req_body)
        return simplejson.loads(body)
    
    def call_method(self, method_name, method='GET', **params):
        url = urlparse.urljoin(self.base_url, method_name+'.json')
        return self.request(url, method=method, **params)

    def get_types(self):
        types = self.call_method('meta_getTypesList')
        types_list = types['servicetypeslist']
        result = {}
        for item in types_list:
            assert len(item) == 1
            item = item['servicetype']
            assert len(item) == 2
            t = item[0]['servicetype']
            code = item[1]['servicecode']
            result[code] = ServiceType(self, t, code)
        return result

    def get_type_definition(self, servicecode):
        definition = self.call_method('meta_getTypeDefinition', servicecode=servicecode)
        definition = definition['servicetypedefinition']
        servicetype = None
        questions = []
        for item in definition:
            item = merge_dict(item['servicetype'])
            servicetype = item['servicetype']
            questions.append(ServiceTypeQuestion(
                name=item['name'],
                prompt=item['prompt'],
                required=asbool(item['required']),
                type=item['type'].strip(),
                width=asint(item.get('width')),
                itemlist=aslist(item.get('itemlist'))
                ))
        return Definition(servicetype, servicecode, questions)
    
    def get(self, servicerequestid):
        return self.call_method('get', servicerequestid=servicerequestid)

    def submit(self, aid, description, **params):
        params['aid'] = aid
        params['description'] = description
        return self.call_method('submit', method='POST', **params)

    def get_from_token(self, token):
        return self.call_method('getFromToken', token=token)
    
class ServiceType(object):

    def __init__(self, service, type, code):
        self.service = service
        self.type = type
        self.code = code
        self._definition = None

    def __repr__(self):
        if self.service.is_default():
            s = ''
        else:
            s = ' (for %r)' % self.service
        return '<%s %s:%s%s>' % (
            self.__class__.__name__,
            self.type,
            self.code,
            s)

    def definition(self):
        if self._definition is None:
            self._definition = self.service.get_type_definition(self.code)
        return self._definition

class ServiceTypeQuestion(object):
    def __init__(self, name, prompt, required, type, width, itemlist):
        self.name = name
        self.prompt = prompt
        self.required = required
        self.type = type
        self.width = width
        self.itemlist = itemlist

    def __repr__(self):
        args = ['name=%s' % self.name,
                'prompt=%r' % self.prompt]
        if self.required:
            args.append('required')
        args.append('type=%s' % self.type)
        if self.width:
            args.append('width=%r' % self.width)
        if self.itemlist:
            args.append('itemlist=%s' % ','.join(self.itemlist))
        return '<%s %s>' % (self.__class__.__name__,
                            ' '.join(args))

class Definition(object):

    def __init__(self, type, code, questions):
        self.type = type
        self.code = code
        self.questions = questions

    def __repr__(self):
        return '<%s %s:%s q=%r>' % (
            self.__class__.__name__,
            self.type, self.code,
            self.questions)
    
def asbool(value):
    if not isinstance(value, basestring):
        return bool(value)
    value = value.strip().lower()
    if value in ('1', 'y', 'yes', 't', 'true', 'on'):
        return True
    if value in ('0', 'n', 'no', 'f', 'false', 'off'):
        return False
    raise ValueError('Unknown boolean: %r' % value)

def asint(value):
    if value is None or value == '':
        return None
    return int(value)

def aslist(value):
    value = value.strip()
    if not value:
        return None
    return value.split(',')

def merge_dict(dicts):
    d = dicts[0]
    for item in dicts[1:]:
        d.update(item)
    return d
