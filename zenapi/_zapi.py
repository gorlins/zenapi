"""Low-level wrapping of the zen api into Python"""
"""
    Copyright 2009 Scott Gorlin

    This file is part of the python package Zenapi.

    Zenapi is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    Zenapi is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with Zenapi.  If not, see <http://www.gnu.org/licenses/>.
"""

# Inspired by Michael J. Wiacek Jr.

import hashlib
import logging
import simplejson
import struct
import urllib
import urllib2
import os
import datetime
import re
import random
import operator
import threading
#import Queue

class Error(Exception):
    pass

class HttpError(Error):
    def __init__(self, code=None, headers=None, url=None, body=None):
        Error.__init__(self)
        self.code = code
        self.headers = headers
        self.url = url
        self.body = body

def MakeRequest(method, params, auth=None, use_ssl=True):
    headers = {'Content-Type': 'application/json',
               'User-Agent': 'Zenapi (Python) Library',
               'X-Zenfolio-User-Agent': 'Zenapi (Python) Library'}

    if auth is not None:
        headers['X-Zenfolio-Token'] = auth

    if use_ssl is False and auth is None:
        url = 'http://www.zenfolio.com/api/1.2/zfapi.asmx'
    else:
        url = 'https://www.zenfolio.com/api/1.2/zfapi.asmx'

    body = '{ "method": "%s", "params": %s' % (method, params)
    body += ', "id": %d }' % random.randint(1, 2**16 - 1)

    headers['Content-Length'] = len(body)

    try:
        req = urllib2.Request(url, body, headers)
        return urllib2.urlopen(urllib2.Request(url, body, headers))
    except urllib2.HTTPError, e:
        raise HttpError(code=e.code, headers=e.headers, url=e.url,body=e.read())

class RpcError(Error):
    def __init__(self, code=None, message=None):
        Error.__init__(self)
        self.code = code
        self.message = message


def PackParams(*args):
    def pullResponse(a):
        if isinstance(a, ResponseObject):
            return a.asdict()
        return a
    return simplejson.dumps(map(pullResponse, args))

"""
Meta framework
"""
class ResponseObjectBuilder(type):
    __registered_types__={}
        
    def __new__(cls, name, bases, attrs):
        parentfields = []
        b = bases[0] #only support 1st base for now
        while b:
            if hasattr(b, '__fields__'):
                parentfields.extend(b.__fields__)
            b = b.__base__
            
        myfields = list(tuple(attrs.get('__fields__', [])))# lazy copy
        
        attrs['__allfields__'] = parentfields + myfields
        
        for f in myfields:
            attrs[f] = cls.getMethod(f)
            
        new_class = super(ResponseObjectBuilder, cls).__new__(cls, name,
                                                              bases, attrs)
        ResponseObjectBuilder.__registered_types__[name]=new_class
        return new_class
    
    @staticmethod
    def getMethod(name):
        def _get(self):
            return self._dict[name]
        def _set(self, val):
            self._dict[name] = val
        return property(fget=_get, fset=_set)
    
class ResponseObject(object):
    __fields__ = []
    __metaclass__ = ResponseObjectBuilder
    
    def __init__(self, *anydicts, **kwargs):
        for d in anydicts:
            kwargs.update(d)
        self._dict = kwargs
        if '$type' in kwargs:
            assert kwargs['$type'] == self.__class__.__name__
            
        for f in self.__allfields__:
            self._dict[f] = kwargs.get(f, None)
        extra = set(kwargs.keys()) - set(self.__allfields__)
        if len(extra):
            Warning('No fields %s in class %s'%(list(extra),
                                                self.__class__.__name__))
            
    def update(self, dictOrRO):
        if isinstance(dictOrRO, ResponseObject):
            ro = dictOrRO.asdict()
        else:
            ro = dictOrRO
        for k,v in ro.items():
            if isinstance(self._dict[k], ResponseObject):
                self._dict[k].update(v)
            elif isinstance(v, list) or isinstance(v, tuple):
                if self._dict[k] and isinstance(self._dict[k][0], ResponseObject):
                    [ss.update(vv) for (ss, vv) in zip(self._dict[k], v)]
                else:
                    self._dict[k] = ResponseObject.build(v)
            else:
                self._dict[k] = v
                
    def setIfNone(self, key, val):
        if hasattr(self._dict, key) and self._dict[key] is None:
            return
        self._dict[key] = val
    
    def asdict(self):
        d = {'$type':self.__class__.__name__}
        for k,v in self._dict.items():
            if isinstance(v, list) or isinstance(v, tuple):
                d[k] = [ResponseObject.__singulartodict(vv) for vv in v]
            elif v is not None:
                d[k] = ResponseObject.__singulartodict(v)
        return d
    
    @staticmethod
    def __singulartodict(obj):
        if isinstance(obj, ResponseObject):
            return obj.asdict()
        return obj
        
    @staticmethod
    def build(obj):
        """Builds a response object from a dictionary"""

        if isinstance(obj, list) or isinstance(obj, tuple):
            return [ResponseObject.build(o) for o in obj]
        if not isinstance(obj, dict):
            return obj
        
        rodict = {}
        for k,v in obj.items(): # Recursively builds responses
            rodict[k] = ResponseObject.build(v)
            
        try:
            types = ResponseObject.__metaclass__.__registered_types__
            return types[rodict['$type']](rodict)
        except KeyError:
            return rodict
        
    
class DateTime(ResponseObject):
    __fields__ = ['Value']
    d4='(\d{4,})'
    d2='(\d{2,})'
    datematch = re.compile(''.join([d4,'-',d2,'-',d2,' ',d2,':',d2,':',d2]))
    
    def __init__(self, *args, **kwargs):
        ResponseObject.__init__(self, *args, **kwargs)
        self.Value = DateTime.str2d(self.Value)
        
    def asdict(self):
        return {'$type':'DateTime', 'Value':DateTime.d2str(self.Value)}
    
    @staticmethod
    def str2d(s):
        groups = DateTime.datematch.match(s).groups()
        return datetime.datetime(*[int(ss) for ss in groups])
    
    @staticmethod
    def d2str(d):
        return '%04i-%02i-%02i %02i:%02i:%02i'%(d.year,
                                                d.month,
                                                d.day,
                                                d.hour,
                                                d.minute, 
                                                d.second)
                                        
    
"""
Updaters
"""
class Updater(ResponseObject):
    pass

class AccessUpdater(Updater):
    """Controlls public/private access to a Zenfolio resource
    
    For details, see:
    http://www.zenfolio.com/zf/help/api/ref/objects/accessmask
    """
    
    __fields__ = ['AccessMask', 'AccessType', 'Viewers', 'Password', 'IsDerived']
    
    masks = ('None', 'HideDateCreated', 'HideDateModified',
             'HideDateTaken', 'HideMetaData', 'HideUserStats',
             'HideVisits', 'NoCollections', 'NoPrivateSearch',
             'NoPublicSearch', 'NoRecentList', 'ProtectExif',
             'ProtectExtraLarge', 'ProtectLarge', 'ProtectMedium',
             'ProtectOriginals', 'ProtectGuestbook',
             'NoPublicGuestbookPosts', 'NoPrivateGuestbookPosts',
             'NoAnonymousGuestbookPosts', 'ProtectComments',
             'NoPublicComments', 'NoPrivateComments',
             'NoAnonymousComments', 'ProtectAll')
    
    #AccessMask = ', '.join(list of masks)
    types = ('Private', 'Public', 'UserList', 'Password')

class CommonUpdater(Updater):
    __fields__ = ['Title', 'Caption']
    
class GroupUpdater(CommonUpdater):
    __fields__ = ['CustomReference']
    
class PhotoSetUpdater(CommonUpdater):
    __fields__ = ['Keywords', 'Categories', 'CustomReference']

class PhotoUpdater(CommonUpdater):
    __fields__ = ['Keywords', 'Categories', 'Copyright', 'FileName']


def Call(method, auth=None, use_ssl=False, params=None):
    if params is None:
        params = '[]'

    try:
        resp = MakeRequest(method, params, auth, use_ssl)
    except HttpError, e:
        logging.warning('ZenFolio API Call for %s failed with params: %s\n'
                        'response code %d with body:\n %s', method, params,
                        e.code, e.body)
        raise Error
    else:
        response = resp.read()
        rpc_obj = simplejson.loads(response)
        if rpc_obj['error'] is None:
            return rpc_obj['result']
        else:
            if 'code' in rpc_obj['error']:
                raise RpcError(
                    message=rpc_obj['error']['message'], 
                    code=rpc_obj['error']['code'])
            else:
                raise RpcError(message=rpc_obj['error']['message'])
"""
Snapshots
"""
    
class Snapshot(ResponseObject):
    __metaclass__ = ResponseObjectBuilder

    __reprkeys__=['Title']
    
    def __repr__(self):
        r = "<%s snapshot: "%self.__class__.__name__
        r += ', '.join([f+": '%s'"%self._dict.get(f,None) for f in self.__reprkeys__ ])
        return r+'>'

class User(Snapshot):
    __reprkeys__=['LoginName']
    __fields__ = ['LoginName', 'DisplayName', 'FirstName', 'LastName', 
                  'PrimaryEmail', 'BioPhoto', 'Bio', 'Views', 'GalleryCount',
                  'CollectionCount', 'PhotoCount', 'PhotoBytes', 'UserSince',
                  'LastUpdated', 'PublicAddress', 'PersonalAddress',
                  'RecentPhotoSets', 'FeaturedPhotoSets', 'RootGroup',
                  'ReferralCode', 'ExpiresOn', 'Balance', 'DomainName',
                  'StorageQuota', 'PhotoBytesQuota']

class GalleryElement(Snapshot):
    __fields__ = ['Title', 'Id', 'AccessDescriptor', 'Owner',
                  'Caption', 'PageUrl']
    
    def __int__(self):
        return self.Id
    
    class ThreadLoader(threading.Thread):
        def __init__(self, ge, zc, *args, **kwargs):
            threading.Thread.__init__(self, *args, **kwargs)
            self.ge = ge
            self.zc = zc
            
        def run(self):
            ro = getattr(self.zc, 'Load'+self.ge.__class__.__name__)(self.ge)
            self.ge.update(ro)


class GroupElement(GalleryElement):
    __reprkeys__=['Title', 'Id']
    __fields__ = ['GroupIndex', 'CreatedOn', 'ModifiedOn', 'PhotoCount',
                  'ParentGroups', 'TitlePhoto']
    
    def get(self, title, field, cls):
        objs = [o for o in self._dict[field] if isinstance(o, cls) and o.Title==title]
        if len(objs) == 0:
            return None
        if len(objs)>1:
            Warning('More than one %s with title "%s"!!'%(cls.__name__, title))
        return objs[0]
    
class Group(GroupElement):
    __fields__ = ['CollectionCount', 'SubGroupCount', 'GalleryCount', 'Elements']
    
    def getGroup(self, title):
        return self.get(title, 'Elements', Group)
    
    def getPhotoSet(self, title):
        return self.get(title, 'Elements', PhotoSet)
    
class PhotoSet(GroupElement):
    __fields__ = ['PhotoBytes', 'Views', 'Type', 'FeaturedIndex', #'TitlePhoto', 
                  'IsRandomTitlePhoto', 'Photos', 'Keywords', 'Categories',
                  'UploadUrl']
            
    def getPhoto(self, title):
        return self.get(title, 'Photos', Photo)
        
class Photo(GalleryElement):
    __reprkeys__=['Title', 'FileName', 'Id']
    __fields__ = ['Width', 'Height', 'Sequence', 'FileName', 'UploadedOn',
                  'TakenOn', 'Gallery', 'OriginalUrl', 'Size', 'MimeType', 
                  'PricingKey', 'Views', 'UrlCore', 'Copyright', 'Rotation', 
                  'FileHash']
    
    Original = None
    
    ThumbRegular = 0
    ThumbSquare = 1
    ThumbLarge = 10
    ImSmall = 2
    ImMed = 3
    ImLarge = 4
    ImXLarge = 5
    
    ProfileLarge = 50
    ProfileSmall = 51
    ProfileRegular = 52
    
    def getUrl(self, size=Original):
        """Calculates the url to any of the resized versions
        See: http://www.zenfolio.com/zf/help/api/guide/download
        Could add port and seq # here, ignoring for now
        """
        if size is None:
            return self.OriginalUrl
        
        return "www.zenfolio.com%s-%s.jpg"%(self.UrlCore, size)
    


"""
Formal API
"""

class ZenConnection(object):
    def __init__(self, username=None, password=None, filename=None):
        self.auth = None
        if filename:
            z = ZenConnection.load(filename)
            username = z.__username
            password = z.__password
        self.__username = username
        self.__password = password

    class _threadcaller(threading.Thread):
        def __init__(self, method, args, **kwargs):
            threading.Thread.__init__(self, **kwargs)
            if not operator.isSequenceType(args):
                args = ((args,), {})
            self.setargs(method, args[0], args[1])
            
        def setargs(self, method, methodargs, methodkwds):
            self._response=None
            self._method=method
            self._methodargs = methodargs
            self._methodkwds = methodkwds
            
        def run(self):
            self._response=self._method(*self._methodargs, **self._methodkwds)
            
        def getResponse(self):
            self.join()
            return self._response
        
    def map(self, method, arglist):
        """Runs a given method in parallel threads
        method: str method name to call
        
        arglist: list of all args in parallell
        ie arglist[0] = ((arg1, arg2, arg3), kwargs)
        alternatively, if the method only requres a single argument, then
        a plain sequence is also accepted
        ie z.map(z.LoadPhotoSet, [p1, p2, p3...])
        
        returns list of all outputs
        """
        if isinstance(method, str):
            method = getattr(self, method)
        #if not operator.isSequenceType(arglist[0]):
            #arglist = [((a,), {}) for a in arglist]
        threads = [self._threadcaller(method, a) for a in arglist]
        #threads = [threading.Thread(target=method,
                                    #args=a[0], 
                                    #kwargs=a[1]) for a in arglist]
        [t.start() for t in threads]
        return [t.getResponse() for t in threads]
                                      
    def save(self, filename):
        import cPickle
        tmpauth = self.auth
        self.auth = None
        f = file(filename, mode='w')
        cPickle.dump(self, f)
        f.close()
        self.auth = tmpauth
        
    @staticmethod
    def load(filename):
        import cPickle
        f = file(filename)
        zapi = cPickle.load(f)
        f.close()
        return zapi
    
    def call(self, method, useMyAuthentication=True, **kwargs):
        if useMyAuthentication:
            kwargs['auth']=self.auth
        return ResponseObject.build(Call(method, **kwargs))
    
    """
    Authentication
    """
    
    def GetChallenge(self):
        return self.call('GetChallenge', params=PackParams(self.__username))

    def AuthenticatePlain(self):
        self.auth = self.call('AuthenticatePlain', use_ssl=True, 
                              params=PackParams(self.__username, self.__password))
        
    def Authenticate(self):
        auth_challenge = self.GetChallenge()
        salt = ''.join([chr(x) for x in auth_challenge['PasswordSalt']])
        challenge = ''.join([chr(x) for x in auth_challenge['Challenge']])

        combo = salt + self.__password.encode('utf-8')
        h2 = hashlib.sha256(combo)
        combo = challenge + h2.digest()
        h1 = hashlib.sha256(combo)
        proof = h1.digest()

        byte_proof = struct.unpack('B'*32, proof)

        try:
            resp = self.call('Authenticate',
                             use_ssl=True,
                             params=PackParams(auth_challenge['Challenge'], byte_proof))
        except RpcError, e:
            logging.warning(
                'Authentication failed code: %s and message: %s', e.code, e.message)
        
        else:
            self.auth = resp
    
    """
    Loaders
    """
    
    def LoadPhoto(self, photo):
        return self.call('LoadPhoto', params=PackParams(int(photo)))

    def LoadPhotoSet(self, photoset):
        return self.call('LoadPhotoSet',
                         params=PackParams(int(photoset)))
    
    def AddPhotoToCollection(self, photo, collection):
        return self.call('CollectionAddPhoto',
                         params=PackParams(int(collection), int(photo)))

    

    def RemovePhotoFromCollection(self, photo, collection):
        return self.call('CollectionRemovePhoto',
                         params=PackParams(int(collection), int(photo)))


    def CreateGroup(self, parent, updater=None):
        if updater is None:
            updater = GroupUpdater()
        assert isinstance(updater, GroupUpdater)
        
        return self.call('CreateGroup',
                         params = PackParams(int(parent), updater))


    def CreatePhotoset(self, parent, photoset_type=None, updater=None):
        if photoset_type not in ('Gallery', 'Collection'):
            raise ValueError('photoset type has invalid valid: %s'%photoset_type)

        if updater is None:
            updater = PhotoSetUpdater()
        assert isinstance(updater, PhotoSetUpdater)

        return self.call('CreatePhotoSet',
                         params=PackParams(int(parent), photoset_type, updater))


    def DeleteGroup(self, group):
        return self.call('DeleteGroup', params=PackParams(int(group)))


    def DeletePhoto(self, photo):
        return self.call('DeletePhoto', params=PackParams(int(photo)))


    def DeletePhotoset(self, photoset):
        return self.call('DeletePhotoSet', params=PackParams(int(photoset)))



    def GetCategories(self):
        return self.call('GetCategories', use_ssl=False)#orig no auth?

    def GetPopularPhotos(self, offset=0, limit=0):
        return self.call('GetPopularPhotos',
                         params=PackParams(offset, limit))


    def GetPopularSets(self, photoset_type=None, offset=0, limit=15):
        if photoset_type not in ('Gallery', 'Collection'):
            raise ValueError('photoset type has invalid valid: %s' % photoset_type)

        return self.call('GetPopularSets',
                         params=PackParams(photoset_type, offset, limit))


    def GetRecentPhotos(self, offset=0, limit=15):
        return self.call('GetRecentPhotos',
                         params=PackParams(offset, limit))

    def GetRecentSets(self, photoset_type=None, offset=0, limit=15):
        if photoset_type not in ('Gallery', 'Collection'):
            raise ValueError('photoset type has invalid valid: %s' % photoset_type)

        return self.call('GetRecentSets',
                         params=PackParams(photoset_type, offset, limit))


    def KeyringAddKeyPlain(self, keyring=None, realmId=None, password=None):
        return self.call('KeyringAddKeyPlain',
                         use_ssl=True,
                         params=PackParams(keyring, realmId, password))


    def LoadGroup(self, group):
        return self.call('LoadGroup',
                         params=PackParams(int(group)))


    def LoadGroupHierarchy(self):
        return self.call('LoadGroupHierarchy',
                         params=PackParams(self.__username))


    def LoadPhoto(self, photo):
        return self.call('LoadPhoto',
                         params=PackParams(int(photo)))


    def LoadPhotoSet(self, photoset):
        return self.call('LoadPhotoSet',
                         params=PackParams(int(photoset)))


    def LoadPrivateProfile(self):
        return self.call('LoadPrivateProfile', auth=self.auth)

    def LoadPublicProfile(self):
        return self.call('LoadPublicProfile', auth=self.auth, params=PackParams(self.__username))


    def MoveGroup(self, group, dest_group, index):
        return self.call('MoveGroup',
                         params=PackParams(int(group), int(dest_group), index))


    def MovePhoto(self, src_set, photo, dest_set, index):
        return self.call('MovePhoto',
                    params=PackParams(int(src_set), int(photo), int(dest_set), index))


    def MovePhotoSet(self, photoset, dest_group, index):
        return self.call('MovePhotoSet',
                         params=PackParams(int(photoset), int(dest_group), index))


    def ReorderGroup(self, group, group_shift_order):
        if group_shift_order not in ('CreatedAsc', 'CreatedDesc', 'ModifiedAsc',
                                     'ModifiedDesc', 'TitleAsc', 'TitleDesc',
                                     'GroupsTop', 'GroupsBottom'):
            raise ValueError('group shift order is invalid!')

        return self.call('ReorderGroup',
                         params=PackParams(int(group), group_shift_order))


    def ReorderPhotoSet(self, photoset, shift_order):
        if shift_order not in ('CreatedAsc', 'CreatedDesc', 'TakenAsc',
                               'TakenDesc', 'TitleAsc', 'TitleDesc', 'SizeAsc',
                               'SizeDesc', 'FileNameAsc', 'FileNameDesc'):
            raise ValueError('shift order is invalid!')

        return self.call('ReorderPhotoSet',
                         params=PackParams(int(photoset), shift_order))


    def ReplacePhoto(self, original_photo, replacement_photo):
        return self.call('ReplacePhoto',
                         params=PackParams(int(original_photo), int(replacement_photo)))


    def RotatePhoto(self, photo, photo_rotation):

        if photo_rotation not in ('None', 'Rotate90', 'Rotate180', 'Rotate270',
                                  'Flip', 'Rotate90Flip', 'Rotate180Flip',
                                  'Rotate270Flip'):
            raise ValueError('photo_rotation order is invalid!')

        return self.call('RotatePhoto',
                         params=PackParams(int(photo), photo_rotation))


    def SearchPhotoByCategory(self, searchId=None,
                              sort_order=None,
                              category_code=None,
                              offset=0,
                              limit=15):
        if sort_order not in ('Date', 'Popularity'):  # Rank is not applicable
            if sort_order is not None:
                raise ValueError('sort_order is not valid!')

        
        return self.call('SearchPhotoByCategory',
                         params=PackParams(searchId,
                                           sort_order,
                                           category_code,
                                           offset,
                                           limit))


    def SearchPhotoByText(self, searchId=None,
                          sort_order=None,
                          query=None,
                          offset=0,
                          limit=15):
        if sort_order not in ('Date', 'Popularity', 'Rank'):
            if sort_order is not None:
                raise ValueError('sort_order is not valid!')

        return self.call('SearchPhotoByText',
                         params=PackParams(searchId,
                                           sort_order,
                                           query,
                                           offset,
                                           limit))


    def SearchSetByCategory(self, searchId=None,
                            photoset_type=None,
                            sort_order=None,
                            category_code=None,
                            offset=0,
                            limit=15):
        if sort_order not in ('Date', 'Popularity'):  # Rank is not applicable
            if sort_order is not None:
                raise ValueError('sort_order is not valid!')

            if photoset_type not in ('Gallery', 'Collection'):
                raise ValueError('photoset type has invalid valid: %s' % photoset_type)

        return self.call('SearchSetByCategory',
                         params=PackParams(searchId,
                                           photoset_type,
                                           sort_order,
                                           category_code,
                                           offset,
                                           limit))


    def SearchSetByText(self, searchId=None,
                        photoset_type=None,
                        sort_order=None,
                        query=None,
                        offset=0,
                        limit=15):
        if sort_order not in ('Date', 'Popularity', 'Rank'):
            if sort_order is not None:
                raise ValueError('sort_order is not valid!')

        return self.call('SearchSetByText',
                         params=PackParams(searchId,
                                           photoset_type,
                                           sort_order,
                                           query,
                                           offset,
                                           limit))


    def SetGroupTitlePhoto(self, group, photo):
        return self.call('SetGroupTitlePhoto',
                         params=PackParams(int(group), int(photo)))


    def SetPhotoSetFeaturedIndex(self, photoset, index):
        return self.call('SetPhotoSetFeaturedIndex',
                         params=PackParams(int(photoset), index))


    def SetPhotoSetTitlePhoto(self, photoset, photo):
        return self.call('SetPhotoSetTitlePhoto',
                         params=PackParams(int(photoset), int(photo)))

    """
    Updaters
    """

    def UpdateGroup(self, group, updater):
        assert isinstance(updater, GroupUpdater)
        return self.call('UpdateGroup', params=PackParams(group, updater))


    def UpdatePhoto(self, photo, updater):
        assert isinstance(updater, PhotoUpdater)

        return self.call('UpdatePhoto',
                         params=PackParams(int(photo), updater))

    def UpdatePhotoSet(self, photoset, updater):
        assert isinstance(updater, PhotoSetUpdater)

        return self.call('UpdatePhotoSet',
                         params=PackParams(int(photoset), updater))
    
    def UpdateGroupAccess(self, group, updater):
        assert isinstance(updater, AccessUpdater)
        return self.call('UpdateGroupAccess',
                         params=PackParams(int(group), updater))

    def UpdatePhotoAccess(self, photo, updater):
        assert isinstance(updater, AccessUpdater)
        return self.call('UpdatePhotoAccess',
                         params=PackParams(int(photo), updater))


    def UpdatePhotoSetAccess(self, photoset, updater):
        assert isinstance(updater, AccessUpdater)
        return self.call('UpdatePhotoSetAccess',
                         params=PackParams(int(photoset), updater))

    """
    Extras not part of the api
    """
    
    def loadFullGroupHierarchy(self):
        """In contrast to the API, loads the hierarchy plus all photosets and
        photos"""

        threads = []

        def recurse(elements):
            for e in elements:
                if isinstance(e, PhotoSet):
                    t = GalleryElement.ThreadLoader(e, self)
                    t.start()
                    threads.append(t)
                elif isinstance(e, Group):
                    recurse(e.Elements)
                    
        h = self.LoadGroupHierarchy()
        recurse(h.Elements)
        [t.join() for t in threads]
        return h
        
    def upload(self, photoset, file_name, autoFillUpdater=True, updater=None, 
               filenameStripRoot=True):
        """Uploads a photo
        
        :Parameters:
          photoset: the Gallery photoset object that will be the parent
          file_name: absolute path to photo on local machine
          autoFillUpdater: puts the filename into Title and Caption
          updater: PhotoUpdater instance to set anything else
          filenameStripRoot: controls how the original file path appears on 
            Zenfolio (ie for zipped downloads, in metadata, etc).  If True,
            strips the path from the filename.  If a string, it sends the
            relative path from a directory (ie C:\My Documents\Me\Awesome.jpg 
            with a root C:\My Documents will become Me\Awesome.jpg)
        """
        import email.Utils

        if not photoset.Type == 'Gallery':
            raise TypeError('Photoset must be a gallery to support uploads')

        f = open(file_name, "rb")
        data = f.read()
        f.close()
        
        size = len(data)
        #f.seek(0)
        #if date_modified:
            #modified = email.Utils.formatdate (time.mktime (date_modified.timetuple()))
        #else:
        #modified = email.Utils.formatdate (os.path.getmtime (file_name))
                     
        fname = os.path.basename (file_name)

        headers = {'User-Agent': 'PyZenfolio Library',
                   'X-Zenfolio-User-Agent': 'PyZenfolio Library'}
        
        headers['Content-Type'] = 'image/jpeg'
        headers['Content-Length'] = len(data)
        
        assert self.auth is not None
        headers['X-Zenfolio-Token'] = self.auth

        upload_url = photoset.UploadUrl
        if filenameStripRoot is True:
            zfilename = os.path.basename(file_name)
        elif isinstance(filenameStripRoot, str):
            zfilename = os.path.relpath(file_name, filenameStripRoot)
        else:
            zfilename = file_name
            
        url = upload_url + '?' + urllib.urlencode ([("filename", zfilename)])#, ("modified", modified)])
        req = urllib2.Request(upload_url, data=data, headers=headers)
        opener = urllib2.build_opener(urllib2.HTTPHandler(debuglevel=0))
        
        try:
            result = simplejson.loads(opener.open(req).read())
            #result = self.LoadPhoto(Photo({'Id':result}))
            if updater is None:
                updater = PhotoUpdater()
            assert isinstance(updater, PhotoUpdater)
            if autoFillUpdater:
                updater.setIfNone('Title', os.path.basename(file_name))
                updater.setIfNone('FileName', zfilename)
            result = self.UpdatePhoto(Photo({'Id':result}), updater)
            #LOG.debug ("RESPONSE: --\n%s\n--\n" % data)
            #result = simplejson.loads(data)
            # TBD : check for erorr by checking the status of the HTTP message
        except Exception, e:
            print e
            raise RuntimeError

        return result


if __name__ == '__main__':
    # some simple testing
    from time import time
    zapi = ZenConnection(username='demo')
    h = zapi.LoadGroupHierarchy()
    hh = zapi.loadFullGroupHierarchy()
    g = zapi.LoadGroup(h.Id) # should be the same as h
    photosets = [p for p in h.Elements if isinstance(p, PhotoSet)]

    # loads serially
    t0 =time()
    loadedSer = [zapi.LoadPhotoSet(p) for p in photosets]
    print time()-t0
    
    # loads parallel
    t0 = time()
    loadedPar = zapi.map(zapi.LoadPhotoSet, photosets)
    print time()-t0
    
    ps = zapi.LoadPhotoSet(photosets[0])
    ph = zapi.LoadPhoto(ps.Photos[0])
    
    h.update(g) # shouldn't change anything
    pass
    
