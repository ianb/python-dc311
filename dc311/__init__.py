import httplib2
import urllib
import urlparse
from datetime import datetime
import time
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
                 apikey=None, http=http, **classes):
        if not base_url.endswith('/'):
            base_url += '/'
        self.base_url = base_url
        self.apikey = apikey
        self.http = http
        for name, value in classes.items():
            if not hasattr(self, name):
                raise TypeError('Bad keyword argument: %s=%r' % (name, value))
            setattr(self, name, value)

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
        """True if this instance was instantiated (effectively) with
        no arguments"""
        return (self.base_url == self.default_base_url
                and not self.apikey
                and self.http is http)
    
    def _request(self, url, method='GET', **params):
        """Call a request"""
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
    
    def _call_method(self, method_name, method='GET', **params):
        """Call a method, returning the parsed JSON response"""
        url = urlparse.urljoin(self.base_url, method_name+'.json')
        return self._request(url, method=method, **params)

    def get_types(self):
        """Get all the service request types, returned as a dictionary.

        The dictionary uses the service request code as the key, and a
        :class:`ServiceType` object as the value.
        """
        types = self._call_method('meta_getTypesList')
        types_list = types['servicetypeslist']
        result = {}
        for item in types_list:
            assert len(item) == 1
            item = item['servicetype']
            assert len(item) == 2
            t = item[0]['servicetype']
            code = item[1]['servicecode']
            result[code] = self.ServiceType(self, t, code)
        return result

    def get_type_definition(self, servicecode):
        """Get the :class:`Definition` for the given service request type"""
        definition = self._call_method('meta_getTypeDefinition', servicecode=servicecode)
        definition = definition['servicetypedefinition']
        servicetype = None
        questions = []
        for item in definition:
            item = merge_dict(item['servicetype'])
            servicetype = item['servicetype']
            if item['name'] == 'NULL':
                continue
            questions.append(self.ServiceTypeQuestion(
                name=item['name'],
                prompt=item['prompt'],
                required=asbool(item['required']),
                type=clean_str(item['type']),
                width=asint(item.get('width')),
                itemlist=aslist(item.get('itemlist'))
                ))
        return self.Definition(servicetype, servicecode, questions)
    
    def get(self, servicerequestid):
        result = self._call_method('get', servicerequestid=servicerequestid)
        result = merge_dict(result['servicerequest'])
        #assert 0, result
        return ServiceRequest(
            code=result['servicecode'],
            codedescription=result['servicecodedescription'],
            typecode=result['servicetypeocode'],
            typecodedescription=result['servicetypecodedescription'],
            priority=clean_str(result['servicepriority']),
            orderstatus=result['serviceorderstatus'],
            agencyabbreviation=result['agencyabbreviation'],
            notes=clean_str(result['servicenotes']),
            resolutiondate=as_date(result['resolutiondate']),
            orderdate=as_date(result['serviceorderdate']),
            duedate=as_date(result['serviceduedate']),
            aid=result['aid'],
            request_id=result['servicerequestid'],
            resolution=clean_str(result['resolution']))

    def submit(self, aid, description, **params):
        for name in params.keys():
            if name.upper() == name:
                new_name = name.replace('_', '-')
                params[new_name] = params.pop(name)
        params['aid'] = aid
        params['description'] = description
        result = self._call_method('submit', method='POST', **params)
        return result['token']

    def get_from_token(self, token):
        result = self._call_method('getFromToken', token=token)
        return result['servicerequestid']
    
class ServiceType(object):
    """Represents a service request type.  Call :method:`definition()`
    to get the full definition."""

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

Service.ServiceType = ServiceType

class ServiceTypeQuestion(object):
    """Represents one question that may need to be answered to submit
    a service request"""
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

Service.ServiceTypeQuestion = ServiceTypeQuestion

class Definition(object):
    """Represents the richer definition of a :class:`ServiceType`"""

    def __init__(self, type, code, questions):
        self.type = type
        self.code = code
        self.questions = questions

    def __repr__(self):
        return '<%s %s:%s q=%r>' % (
            self.__class__.__name__,
            self.type, self.code,
            self.questions)

Service.Definition = Definition

class ServiceRequest(object):
    def __init__(self, code, codedescription,
                 typecode, typecodedescription,
                 priority, orderstatus, agencyabbreviation,
                 notes, resolutiondate,
                 orderdate, duedate, aid, request_id,
                 resolution):
        self.code = code
        self.codedescription = codedescription
        self.typecode = typecode
        self.typecodedescription = typecodedescription
        self.priority = priority
        self.orderstatus = orderstatus
        self.agencyabbreviation = agencyabbreviation
        self.notes = notes
        self.resolutiondate = resolutiondate
        self.orderdate = orderdate
        self.duedate = duedate
        self.aid = aid
        self.request_id = request_id
        self.resolution=resolution

    def __repr__(self):
        args = []
        for key in ('code codedescription typecode typecodedescription '
                    'priority orderstatus agencyabbreviation notes '
                    'resolutiondate orderdate duedate aid resolution').split():
            value = getattr(self, key)
            if isinstance(value, datetime):
                value = value.strftime('%Y-%m-%d %H:%M:%S')
            else:
                value = repr(value)
            args.append('%s=%s' % (key, value))
        return '<%s %s %s>' % (
            self.__class__.__name__,
            self.request_id,
            ' '.join(args))
    
def asbool(value):
    """Converts a string to a boolean"""
    if not isinstance(value, basestring):
        return bool(value)
    value = value.strip().lower()
    if value in ('1', 'y', 'yes', 't', 'true', 'on'):
        return True
    if value in ('0', 'n', 'no', 'f', 'false', 'off', 'null'):
        return False
    raise ValueError('Unknown boolean: %r' % value)

def asint(value):
    """Converts a string to an int, except empty strings"""
    if value is None or value == '' or value == 'NULL':
        return None
    return int(value)

def aslist(value):
    """Converts a comma-separated string into a list"""
    value = value.strip()
    if not value:
        return None
    return value.split(',')

def merge_dict(dicts):
    d = dicts[0]
    for item in dicts[1:]:
        d.update(item)
    return d

def clean_str(s):
    if s == 'NO VALUE ASSIGNED':
        return None
    if s == 'NULL':
        return None
    return s.strip().replace('\r\n', '\n')

def as_date(s):
    if not s or s == 'NULL':
        return None
    return datetime.fromtimestamp(time.mktime(time.strptime(s, '%Y-%m-%d %H:%M:%S')))
