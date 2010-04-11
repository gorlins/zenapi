
from zenapi import ZenConnection
from zenapi.snapshots import Group, PhotoSet
from zenapi.updaters import PhotoSetUpdater, GroupUpdater

from time import time
from threading import Thread
import Queue

_q = Queue.Queue()

def updateZenTitlePhotos(username, password):
    """Updates the title photo of every PhotoSet and Group to be 
    the most-viewed photo.  Overwrites current title photos
    """
    zen = ZenConnection(username=username, password=password)
    
    
    print 'Loading album hierarchy...'
    t0 = time()
    h = zen.loadFullGroupHierarchy()
    print 'Loaded in %i seconds.'%(time()-t0)    
    zen.Authenticate() # so we only work on the public photos
    
    print 'Updating...'
    
    t1 = time()
    _updateGroup(zen, h)
    def worker():
        while True:
            item = _q.get()
            item.start()
            item.join()
            _q.task_done()
    for i in range(10):
        t = Thread(target=worker)
        t.setDaemon(True)
        t.start()
    _q.join()
    print 'Done in %i seconds'%(time()-t1)
    pass


def _updatePhotoSet(zen, pset):
    views = {}
    for p in pset.Photos:
        views[p.Views] = p
        
    mostViews = max(views.keys())
    mostPopular = views[mostViews]
    if pset.TitlePhoto is None or pset.TitlePhoto.Id != mostPopular.Id:
        pset.TitlePhoto = mostPopular
        _q.put(_UpdatePsPhoto(zen, pset, mostPopular))
        
def _updateGroup(zen, group):
    views = {}
    for element in group.Elements:
        if isinstance(element, Group):
            v = _updateGroup(zen, element)
            views[v] = element.TitlePhoto
        elif isinstance(element, PhotoSet):
            _updatePhotoSet(zen, element)
            views[element.Views] = element.TitlePhoto
    
        
    mostViews = max(views.keys())
    mostPopular = views[mostViews]
    
    if group.TitlePhoto is None or group.TitlePhoto.Id != mostPopular.Id:
        print 'Group %s, popular is %s with %s views'%(group, 
                                                       mostPopular, mostViews)
        group.TitlePhoto = mostPopular
        _q.put(_UpdateGroupPhoto(zen, group, mostPopular))
        
    return mostViews
    
class _UpdateTitlePhoto(Thread):
    def __init__(self, zen, element, photo, **kwargs):
        Thread.__init__(self, **kwargs)
        self.zen = zen
        self.photo = photo
        self.element = element
class _UpdatePsPhoto(_UpdateTitlePhoto):
    def run(self):
        self.zen.SetPhotoSetTitlePhoto(self.element, self.photo)
class _UpdateGroupPhoto(_UpdateTitlePhoto):
    def run(self):
        self.zen.SetGroupTitlePhoto(self.element, self.photo)
    
        
            
if __name__ == '__main__':
    
    updateZenTitlePhotos('myusername', 'mypassword')
