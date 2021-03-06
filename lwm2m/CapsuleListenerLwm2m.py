'''
Created on Sept 22, 2014

System Constructor for resource stub representing the Nespresso Capsule Type String

An agent listens on a socket and discovers the capsule type from the output of Barista

The Agent sets the resource value of 11101/0/5001 Capsule Type Resource to the current type


@author: mjkoster
'''
from core.RESTfulResource import RESTfulResource
from core.SmartObject import SmartObject
from rdflib.term import Literal, URIRef
from interfaces.HttpObjectService import HttpObjectService
from interfaces.CoapObjectService import CoapObjectService
from time import sleep
from urlparse import urlparse
import subprocess
import rdflib
import websocket
import json


#workaround to register rdf JSON plugins 
from rdflib.plugin import Serializer, Parser
rdflib.plugin.register('json-ld', Serializer, 'rdflib_jsonld.serializer', 'JsonLDSerializer')
rdflib.plugin.register('json-ld', Parser, 'rdflib_jsonld.parser', 'JsonLDParser')
rdflib.plugin.register('rdf-json', Serializer, 'rdflib_rdfjson.rdfjson_serializer', 'RdfJsonSerializer')
rdflib.plugin.register('rdf-json', Parser, 'rdflib_rdfjson.rdfjson_parser', 'RdfJsonParser')
'''
model format for populating Description and creating SmartObject instances and service instances
'''
exampleConstructor = {
'service_metadata': {
    'FQDN': '',
    'IPV4': '',
    'IPV6': ''
    },
#replace with unique service URIs e.g. http://localhost:8000  when starting service instances
'services': {
    'localHTTP' : {
        'scheme': 'http',
        'FQDN': 'localhost',
        'port': 8000,
        'IPV4': '',
        'root': '/',
        'discovery': '/'
                    },                
    'localCoAP': {
        'scheme': 'coap',
        'FQDN': 'localhost',
        'port': 5683,
        'IPV4': '',
        'root': '/',
        'discovery': '/' 
                }
             },

'object_metadata': {
    'objectPath': '',
    },

'objects': {
    '/': {
        'resourceName': '/',
        'resourceClass': 'SmartObject'
        },
    '/services': {
        'resourceName': 'services',
        'resourceClass': 'SmartObject'
        },
     '/11101': {
        'resourceName': '11101',
        'resourceClass': 'SmartObject' # LWM2M_Object
        },
    '/11101/0': {
        'resourceName': '0',
        'resourceClass': 'SmartObject' # LWM2M_Instance
        },
    '/11101/0/5001': {
        'resourceName': '5001',
        'resourceClass': 'ObservableProperty', # LWM2M_Resource
        'resourceType': 'CapsuleID',
        'interfaceType':'sensor',
        'dataType':'string',
        },
    '/Agent/BLE_ColorLED_Handler': {
        'resourceName': 'BLE_ColorLED_handler',
        'resourceClass': 'BLE_ColorLED_handler',
        'MACaddress': 'E0:DE:F3:62:42:D7',
        'MACtype': 'random',
        'charHandle': '0x000b'
        },
    '/11100': {
        'resourceName': '11100',
        'resourceClass': 'SmartObject' # LWM2M_Object
        },
    '/11100/0': {
        'resourceName': '0',
        'resourceClass': 'SmartObject' # LWM2M_Instance
        },
    '/11100/0/5900': {
        'resourceName': '5900',
        'resourceClass': 'ObservableProperty', # LWM2M_Resource
        'resourceType': 'ColorLED',
        'interfaceType':'actuator',
        'dataType':'32_bit_hex_string_RRGGBBNN',
        'publishesTo':['http://barista.cloudapp.net:8080/domain/endpoints/LED-booth-10-0-0-44/11100/0/5900?sync=true']
        #'publishesTo':['http://192.168.1.200:8000/11100/0/5900']
        #'handledBy': ['handler:///Agent/BLE_ColorLED_handler']
        },
    }
                      
}

class SystemInstance(object):
    '''
    creates service instances and object instances from dictionary constructors
    {
    'service_metadata': {},
    'services': {},
    'object_metadata': {},
    'objects': {}
    }
    '''
    def __init__(self, systemConstructor):
        
        self._service_metadata = systemConstructor['service_metadata']
        self._services = systemConstructor['services']
        self._object_metadata = systemConstructor['object_metadata']
        self._objects = systemConstructor['objects']
        
        self._baseObject = None
        
        self._defaultResources = {
                                  'SmartObject': ['Description', 'Agent'],
                                  'ObservableProperty': ['Description', 'Observers']
                                  }

        self._observerTypes = ['subscribesTo', 'publishesTo', 'bridgesTo', 'handledBy']
        
        self._observerSchemes = ['http', 'coap', 'mqtt', 'handler']

        self._mqttObserverTemplate = {
                                      'resourceName': 'mqttObserver',
                                      'resourceClass': 'mqttObserver',
                                      'connection': 'localhost',
                                      'pubTopic': '',
                                      'subTopic': '',
                                      'keepAlive': 60,
                                      'QoS': 0
                                      }
        
        self._httpPublisherTemplate = {
                                       'resourceName': 'httpPublisher',
                                       'resourceClass': 'httpPublisher',
                                       'targetURI': 'http://localhost:8000/',
                                       'username': 'admin',
                                       'password': 'secret'
                                       }
        
        self._httpSubscriberTemplate = {
                                        'resourceName': 'httpSubscriber',
                                        'resourceClass': 'httpSubscriber',
                                        'ObserverURI': 'http://localhost:8000/',
                                        }
        
        self._coapPublisherTemplate = {
                                       'resourceName': 'coapPublisher',
                                       'resourceClass': 'coapPublisher',
                                       'targetURI': 'coap://localhost:5683/'
                                       }
        
        self._coapSubscriberTemplate = {
                                        'resourceName': 'coapSubscriber',
                                        'resourceClass': 'coapSubscriber',
                                        'ObserverURI': 'coap://localhost:5683/'
                                        }

        self._callbackNotifierTemplate = {
                                          'resourceName': 'callbackNotifier',
                                          'resourceClass': 'callbackNotifier',
                                          'handlerURI': 'handler://'
                                          }

        '''
        make objects from object models first
        make list sorted by path element count + length for import from graph, 
        could count a split list but this should be the same if we eat slashes somewhere
        having the root object called '/' and '/' as the separator is extra work 
        '''
        self._resourceList = sorted( self._objects.keys(), key=lambda s:s.count('/') )
        self._resourceList = sorted( self._resourceList, key=lambda s:len(s))
        for self._resourceLink in self._resourceList:
            self._resourceDescriptor = self._objects[self._resourceLink]
            # see if base object needs to be created. 
            if self._resourceLink is '/' and self._resourceDescriptor['resourceClass'] is 'SmartObject' and self._baseObject is None:
                self._newResource = SmartObject()
                self._baseObject = self._newResource
            else:
                self._parentLink = '/'.join(self._resourceLink.split('/')[:-1])
                if self._parentLink == '': self._parentLink = '/'
                self._parentObject = self._objectFromPath(self._parentLink, self._baseObject)
                self._newResource = self._parentObject.create( self._resourceDescriptor)
            if self._resourceDescriptor['resourceClass'] in self._defaultResources:
                for self._defaultResource in self._defaultResources[self._resourceDescriptor['resourceClass']]:
                    self._newChildResource = self._newResource.create({
                                        'resourceName': self._defaultResource,
                                        'resourceClass': self._defaultResource
                                        })
                    if self._defaultResource is 'Description': 
                        self._newChildResource.create(self._graphFromModel(self._resourceLink, self._resourceDescriptor))
                        self._newResource.create({'resourceName':'.well-known', 'resourceClass':'Agent'})\
                        .create({'resourceName':'core', 'resourceClass':'LinkFormatProxy'})
                        # FIXME need to aggregate graphs upstream
            # make observers from the list of URIs of each Observer type
            for self._resourceProperty in self._resourceDescriptor:
                if self._resourceProperty in self._observerTypes:
                    for self._observerURI in self._resourceDescriptor[self._resourceProperty]:
                        self._observerFromURI(self._newResource, self._resourceProperty, self._observerURI )
        '''
        make services
        '''
        # make this a service Object (RESTfulResource) with dict as constructor
        self._serviceRegistry = self._objectFromPath('/services', self._baseObject)
        self._serviceDescription = self._objectFromPath('/services/Description', self._baseObject)        
    
        for self._serviceName in self._services:
            self._newService = ServiceObject(self._serviceName, self._services[self._serviceName], self._baseObject)
            self._serviceRegistry.resources.update({self._serviceName:self._newService})
            self._serviceDescription.set(self._graphFromModel(self._serviceName, self._services[self._serviceName]))

                
    def _graphFromModel(self, link, meta):
        # make rdf-json from the model and return RDF graph for loading into Description
        g=rdflib.Graph()
        subject=URIRef(link)
        for relation in meta:
            value = meta[relation]
            g.add((subject, Literal(relation), Literal(value)))
        return g

    def _observerFromURI(self, currentResource, observerType, observerURI):
        # split by scheme
        URIObject=urlparse(observerURI)
        # fill in constructor template
        if URIObject.scheme == 'http':
            if observerType is 'publishesTo':
                resourceConstructor = self._httpPublisherTemplate.copy()
                resourceConstructor['targetURI'] = observerURI
            if observerType is 'subscribesTo':
                resourceConstructor = self._httpSubscriberTemplate.copy()
                resourceConstructor['observerURI'] = observerURI
    
        elif URIObject.scheme == 'coap':
            if observerType is 'publishesTo':
                resourceConstructor = self._coapPublisherTemplate.copy()
                resourceConstructor['targetURI'] = observerURI
            if observerType is 'subscribesTo':
                resourceConstructor = self._coapSubscriberTemplate.copy()
                resourceConstructor['observerURI'] = observerURI
    
        elif URIObject.scheme == 'mqtt':
            resourceConstructor = self._mqttObserverTemplate.copy() 
            resourceConstructor['connection'] = URIObject.netloc
            if observerType is 'publishesTo':
                resourceConstructor['pubTopic'] = URIObject.path
            if observerType is 'subscribesTo':
                resourceConstructor['subTopic'] = URIObject.path
            if observerType is 'bridgesTo':
                resourceConstructor['pubTopic'] = URIObject.path
                resourceConstructor['subTopic'] = URIObject.path

        elif URIObject.scheme == 'handler':
            resourceConstructor = self._callbackNotifierTemplate.copy()   
            resourceConstructor['handlerURI'] = observerURI
            
        else:
            print 'no scheme', URIObject.scheme
            return
            
        #create resource in currentResource.resources['Observers'] container  
        newObserver = currentResource.resources['Observers'].create(resourceConstructor) 

    def _objectFromPath(self, path, baseObject):
    # fails if resource doesn't exist
        currentObject=baseObject
        pathList = path.split('/')[1:]
        for pathElement in pathList:
            if len(pathElement) > 0:
                currentObject=currentObject.resources[pathElement]
        return currentObject

class ServiceObject(RESTfulResource):
    def __init__(self, serviceName, serviceConstructor, baseObject):
        self._resourceConstructor = {
                               'resourceName': serviceName,
                               'resourceClass': serviceConstructor['scheme']
                               }
        
        RESTfulResource.__init__(self, baseObject, self._resourceConstructor )
        self._serviceConstructor = serviceConstructor
        # TODO collect IP addresses and update the constructor
        if self._serviceConstructor['scheme'] is 'http':
            self._httpService = HttpObjectService\
            (self._objectFromPath(self._serviceConstructor['root'], baseObject), port=self._serviceConstructor['port'])
            URLObject= urlparse(self._httpService._baseObject.Properties.get('httpService'))
            self._serviceConstructor['FQDN'] = URLObject.netloc.split(':')[0]
            
        if self._serviceConstructor['scheme'] is 'coap':
            self._coapService = CoapObjectService\
            (self._objectFromPath(self._serviceConstructor['root'], baseObject), port=self._serviceConstructor['port'])
            URLObject= urlparse(self._coapService._baseObject.Properties.get('coapService'))
            self._serviceConstructor['FQDN'] = URLObject.netloc.split(':')[0]
                
        if serviceConstructor['scheme'] is 'mqtt':
            subprocess.call('mosquitto -d -p ', self._serviceConstructor['port'])
            
        self._set(self._serviceConstructor)

    def _objectFromPath(self, path, baseObject):
    # fails if resource doesn't exist
        currentObject=baseObject
        pathList = path.split('/')[1:]
        for pathElement in pathList:
            if len(pathElement) > 0:
                currentObject=currentObject.resources[pathElement]
        return currentObject


if __name__ == '__main__' :
    
    import httplib
    import json
    from urlparse import urlparse
    import base64
    
    httpServer = 'http://barista.cloudapp.net:8080'
    httpPathBase = '/domain/endpoints'
    basePath = httpServer + httpPathBase
    username = 'admin'
    password = 'secret'
    auth = base64.encodestring('%s:%s' % (username, password)).replace('\n', '')
    ep_names = []

    
    def discoverEndpoints(basePath):
        uriObject = urlparse(basePath)
        httpConnection = httplib.HTTPConnection(uriObject.netloc)
        httpConnection.request('GET', uriObject.path, headers= \
                           {"Accept" : "application/json", "Authorization": ("Basic %s" % auth) })
    
        response = httpConnection.getresponse()
        print response.status, response.reason
        if response.status == 200:
            endpoints = json.loads(response.read())
        httpConnection.close()
            
        return endpoints

    
    def discoverLEDresources(endpoints):
        for endpoint in endpoints:
            if endpoint['type'] == 'mbed_device':
                ep_names.append(endpoint['name'])
        print ep_names        
        return ep_names

    def actuateLEDs(ep_names,color):
        jsonObject = json.dumps(color)
        for ep in ep_names:
            path = basePath + ep + '/11100/0/5900?sync=true'
            uriObject = urlparse(path)
            httpConnection = httplib.HTTPConnection(uriObject.netloc)
            httpConnection.request('PUT',   uriObject.path, jsonObject, \
                                     {"Content-Type" : "application/json", "Authorization": ("Basic %s" % auth)})
            response = httpConnection.getresponse()
            print response.status, response.reason
            httpConnection.close()
    
    
    def capsule2color(capsuleType):
        colorTable = {
        'kazaar':'00005000',
        'dharkan':'00404000',
        'ristretto':'18181000',
        'arpeggio':'20003000',
        'roma':'30302000',
        'livanto':'40100000',
        'capriccio':'00300000',
        'volluto':'50300000',
        'decaffeinato_intenso':'30001800',
        'vivalto_lungo':'20204000'              
        }
        return colorTable[capsuleType]
    
    def processPayload(payload):
        payload = json.loads(payload)
        if payload.has_key('currentCapsule'):
            print payload['currentCapsule']
            actuateLEDs(ep_names, capsule2color(payload['currentCapsule']))
            
            #system._objectFromPath('/11101/0/5001', system._baseObject).set(payload['currentCapsule'])
            #system._objectFromPath('/11100/0/5900', system._baseObject).set(capsule2color(payload['currentCapsule']))
            
    """
    Start
    """
    print "Started"
    #system = SystemInstance(exampleConstructor)

    ep_names = discoverLEDresources(discoverEndpoints(basePath))
           
    ws = websocket.WebSocket()
    ws.connect('ws://localhost:4001/ws')
    #ws.connect('ws://barista.cloudapp.net:4001/ws')
    print 'ws connected'
    try:
        while 1:
            processPayload(ws.recv())
    except KeyboardInterrupt: pass
    print 'got KeyboardInterrupt'
    ws.close()
    print 'closed'
    
    