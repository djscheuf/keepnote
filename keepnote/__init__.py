"""
    KeepNote
    Module for KeepNote
    
    Basic backend data structures for KeepNote and NoteBooks
"""

#
#  KeepNote
#  Copyright (c) 2008-2009 Matt Rasmussen
#  Author: Matt Rasmussen <rasmus@mit.edu>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301, USA.
#



# python imports
import imp
import os
import shutil
import sys
import time
import re
import subprocess
import tempfile
import traceback
import zipfile
try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.elementtree.ElementTree as ET


# work around pygtk changing default encoding
DEFAULT_ENCODING = sys.getdefaultencoding()
FS_ENCODING = sys.getfilesystemencoding()

# keepnote imports
from keepnote.notebook import \
    NoteBookError, \
    get_unique_filename_list
import keepnote.timestamp
import keepnote.notebook
import keepnote.xdg
from keepnote import xmlobject as xmlo
from keepnote.listening import Listeners
from keepnote.util import compose
from keepnote import mswin
import keepnote.trans
from keepnote.trans import GETTEXT_DOMAIN
from keepnote import extension
from keepnote import plist
from keepnote import safefile



#=============================================================================
# modules needed by builtin extensions
# these are imported here, so that py2exe can auto-discover them
from keepnote import tarfile
import xml.dom.minidom
import xml.sax.saxutils
import sgmllib
import htmlentitydefs
import re
import base64
import string
import random

# import screenshot so that py2exe discovers it
try:
    import mswin.screenshot
except ImportError:
    pass



#=============================================================================
# globals / constants

PROGRAM_NAME = u"KeepNote"
PROGRAM_VERSION_MAJOR = 0
PROGRAM_VERSION_MINOR = 6
PROGRAM_VERSION_RELEASE = 4
PROGRAM_VERSION = (PROGRAM_VERSION_MAJOR,
                   PROGRAM_VERSION_MINOR,
                   PROGRAM_VERSION_RELEASE)

if PROGRAM_VERSION_RELEASE != 0:
    PROGRAM_VERSION_TEXT = "%d.%d.%d" % (PROGRAM_VERSION_MAJOR,
                                         PROGRAM_VERSION_MINOR,
                                         PROGRAM_VERSION_RELEASE)
else:
    PROGRAM_VERSION_TEXT = "%d.%d" % (PROGRAM_VERSION_MAJOR,
                                      PROGRAM_VERSION_MINOR)

WEBSITE = u"http://rasm.ods.org/keepnote"
LICENSE_NAME = "GPL version 2"
COPYRIGHT = "Copyright Matt Rasmussen 2010."
TRANSLATOR_CREDITS = (
    "Chinese: hu dachuan <hdccn@sina.com>\n"
    "French: tb <thibaut.bethune@gmail.com>\n"
    "German: Jan Rimmek <jan.rimmek@mhinac.de>\n"
    "Japanese: Toshiharu Kudoh <toshi.kd2@gmail.com>\n"
    "Italian: Davide Melan <davide.melan@gmail.com>\n"
    "Russian: Hikiko Mori <hikikomori.dndz@gmail.com>\n"
    "Spanish: Klemens Hackel <click3d at linuxmail (dot) org>\n"
    "Turkish: Yuce Tekol <yucetekol@gmail.com>\n"
)




BASEDIR = unicode(os.path.dirname(__file__))
IMAGE_DIR = u"images"
NODE_ICON_DIR = os.path.join(IMAGE_DIR, u"node_icons")
PLATFORM = None

USER_PREF_DIR = u"keepnote"
USER_PREF_FILE = u"keepnote.xml"
USER_LOCK_FILE = u"lockfile"
USER_ERROR_LOG = u"error-log.txt"
USER_EXTENSIONS_DIR = u"extensions"
USER_EXTENSIONS_DATA_DIR = u"extensions_data"



DEFAULT_WINDOW_SIZE = (1024, 600)
DEFAULT_WINDOW_POS = (-1, -1)
DEFAULT_VSASH_POS = 200
DEFAULT_HSASH_POS = 200
DEFAULT_VIEW_MODE = "vertical"
DEFAULT_AUTOSAVE_TIME = 10 * 1000 # 10 sec (in msec)



#=============================================================================
# application resources

# TODO: cleanup, make get/set_basedir symmetrical

def get_basedir():
    return unicode(os.path.dirname(__file__))

def set_basedir(basedir):
    global BASEDIR
    if basedir is None:
        BASEDIR = get_basedir()
    else:
        BASEDIR = basedir
    keepnote.trans.set_local_dir(get_locale_dir())


def get_resource(*path_list):
    return os.path.join(BASEDIR, *path_list)


#=============================================================================
# common functions

def get_platform():
    """Returns a string for the current platform"""
    global PLATFORM
    
    if PLATFORM is None:
        p = sys.platform    
        if p == 'darwin':
            PLATFORM = 'darwin'
        elif p.startswith('win'):
            PLATFORM = 'windows'
        else:
            PLATFORM = 'unix'
                    
    return PLATFORM


def is_url(text):
    """Returns True is text is a url"""
    return re.match("^[^:]+://", text) is not None


def ensure_unicode(text, encoding="utf8"):
    """Ensures a string is unicode"""

    # let None's pass through
    if text is None:
        return None

    # make sure text is unicode
    if not isinstance(text, unicode):
        return unicode(text, encoding)
    return text


def unicode_gtk(text):
    """
    Converts a string from gtk (utf8) to unicode

    All strings from the pygtk API are returned as byte strings (str) 
    encoded as utf8.  KeepNote has the convention to keep all strings as
    unicode internally.  So strings from pygtk must be converted to unicode
    immediately.

    Note: pygtk can accept either unicode or utf8 encoded byte strings.
    """
    if text is None:
        return None
    return unicode(text, "utf8")


#=============================================================================
# locale functions

def translate(message):
    """Translate a string"""
    return keepnote.trans.translate(message)

def get_locale_dir():
    """Returns KeepNote's locale directory"""
    return get_resource(u"rc", u"locale")


_ = translate


#=============================================================================
# preference filenaming scheme


def get_home():
    """Returns user's HOME directory"""
    home = ensure_unicode(os.getenv(u"HOME"), FS_ENCODING)
    if home is None:
        raise EnvError("HOME environment variable must be specified")
    return home


def get_user_pref_dir(home=None):
    """Returns the directory of the application preference file"""
    
    p = get_platform()
    if p == "unix" or p == "darwin":
        if home is None:
            home = get_home()
        return keepnote.xdg.get_config_file(USER_PREF_DIR, default=True)

    elif p == "windows":
        appdata = get_win_env("APPDATA")
        if appdata is None:
            raise EnvError("APPDATA environment variable must be specified")
        return os.path.join(appdata, USER_PREF_DIR)

    else:
        raise Exception("unknown platform '%s'" % p)


def get_user_extensions_dir(pref_dir=None, home=None):
    """Returns user extensions directory"""

    if pref_dir is None:
        pref_dir = get_user_pref_dir(home)
    return os.path.join(pref_dir, USER_EXTENSIONS_DIR)
    

def get_user_extensions_data_dir(pref_dir=None, home=None):
    """Returns user extensions data directory"""

    if pref_dir is None:
        pref_dir = get_user_pref_dir(home)
    return os.path.join(pref_dir, USER_EXTENSIONS_DATA_DIR)


def get_system_extensions_dir():
    """Returns system-wide extensions directory"""
    return os.path.join(BASEDIR, u"extensions")


def get_user_documents(home=None):
    """Returns the directory of the user's documents"""
    p = get_platform()
    if p == "unix" or p == "darwin":
        if home is None:
            home = get_home()
        return home
    
    elif p == "windows":
        return unicode(mswin.get_my_documents(), FS_ENCODING)
    
    else:
        return u""
    

def get_user_pref_file(pref_dir=None, home=None):
    """Returns the filename of the application preference file"""
    if pref_dir is None:
        pref_dir = get_user_pref_dir(home)
    return os.path.join(pref_dir, USER_PREF_FILE)


def get_user_lock_file(pref_dir=None, home=None):
    """Returns the filename of the application lock file"""
    if pref_dir is None:
        pref_dir = get_user_pref_dir(home)
    return os.path.join(pref_dir, USER_LOCK_FILE)


def get_user_error_log(pref_dir=None, home=None):
    """Returns a file for the error log"""

    if pref_dir is None:
        pref_dir = get_user_pref_dir(home)
    return os.path.join(pref_dir, USER_ERROR_LOG)


def get_win_env(key):
    """Returns a windows environment variable"""
    # try both encodings
    try:
        return ensure_unicode(os.getenv(key), DEFAULT_ENCODING)
    except UnicodeDecodeError:
        return ensure_unicode(os.getenv(key), FS_ENCODING)


#=============================================================================
# preference/extension initialization

def init_user_pref_dir(pref_dir=None, home=None):
    """Initializes the application preference file"""

    if pref_dir is None:
        pref_dir = get_user_pref_dir(home)

    # make directory
    if not os.path.exists(pref_dir):
        os.makedirs(pref_dir, 0700)

    # init empty pref file
    pref_file = get_user_pref_file(pref_dir)
    if not os.path.exists(pref_file):
        out = open(pref_file, "w")
        out.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
        out.write("<keepnote>\n")
        out.write("</keepnote>\n")
        out.close()

    # init error log
    init_error_log(pref_dir)

    # init user extensions
    extension.init_user_extensions(pref_dir)


def init_error_log(pref_dir=None, home=None):
    """Initialize the error log"""

    if pref_dir is None:
        pref_dir = get_user_pref_dir(home)     

    error_log = get_user_error_log(pref_dir)
    if not os.path.exists(error_log):
        error_dir = os.path.dirname(error_log)
        if not os.path.exists(error_dir):
            os.makedirs(error_dir)
        open(error_log, "a").close()


def log_error(error, tracebk=None, out=None):
    """Write an exception error to the error log"""
    
    if out is None:
        out = sys.stderr

    out.write("\n")
    traceback.print_exception(type(error), error, tracebk, file=out)
    out.flush()


def log_message(message, out=None):
    """Write a message to the error log"""

    if out is None:
        out = sys.stderr
    out.write(message)
    out.flush()



#=============================================================================
# Preference data structures

class ExternalApp (object):
    """Class represents the information needed for calling an external application"""

    def __init__(self, key, title, prog, args=[]):
        self.key = key
        self.title = title
        self.prog = prog
        self.args = args

class AppCommand (object):
    """Application Command"""

    def __init__(self, name, func=lambda app, args: None, 
                 metavar="", help=""):
        self.name = name
        self.func = func
        self.metavar = metavar
        self.help = help


class KeepNotePreferenceError (StandardError):
    """Exception that occurs when manipulating preferences"""
    
    def __init__(self, msg, error=None):
        StandardError.__init__(self)
        self.msg = msg
        self.error = error
        
    def __str__(self):
        if self.error:
            return str(self.error) + "\n" + self.msg
        else:
            return self.msg

class EnvError (StandardError):
    """Exception that occurs when environment variables are ill-defined"""
    
    def __init__(self, msg, error=None):
        StandardError.__init__(self)
        self.msg = msg
        self.error = error
        
    def __str__(self):
        if self.error:
            return str(self.error) + "\n" + self.msg
        else:
            return self.msg


DEFAULT_EXTERNAL_APPS = [
            ExternalApp("file_launcher", "File Launcher", u""),
            ExternalApp("web_browser", "Web Browser", u""),
            ExternalApp("file_explorer", "File Explorer", u""),
            ExternalApp("text_editor", "Text Editor", u""),
            ExternalApp("image_editor", "Image Editor", u""),
            ExternalApp("image_viewer", "Image Viewer", u""),
            ExternalApp("screen_shot", "Screen Shot", u"")
            ]

def get_external_app_defaults():
    if get_platform() == "windows":
        files = ensure_unicode(
            os.environ.get(u"PROGRAMFILES", u"C:\\Program Files"),FS_ENCODING)

        return [
            ExternalApp("file_launcher", "File Launcher", u"explorer.exe"),
            ExternalApp("web_browser", "Web Browser",
                        files + u"\\Internet Explorer\\iexplore.exe"),
            ExternalApp("file_explorer", "File Explorer", u"explorer.exe"),
            ExternalApp("text_editor", "Text Editor",
                        files + u"\\Windows NT\\Accessories\\wordpad.exe"),
            ExternalApp("image_editor", "Image Editor", u"mspaint.exe"),
            ExternalApp("image_viewer", "Image Viewer",
                        files + u"\\Internet Explorer\\iexplore.exe"),
            ExternalApp("screen_shot", "Screen Shot", "")
            ]

    elif get_platform() == "unix":
        return [
            ExternalApp("file_launcher", "File Launcher", u"xdg-open"),
            ExternalApp("web_browser", "Web Browser", u""),
            ExternalApp("file_explorer", "File Explorer", u""),
            ExternalApp("text_editor", "Text Editor", u""),
            ExternalApp("image_editor", "Image Editor", u""),
            ExternalApp("image_viewer", "Image Viewer", u"display"),
            ExternalApp("screen_shot", "Screen Shot", u"import")
            ]
    else:
        return DEFAULT_EXTERNAL_APPS
        



class KeepNotePreferences (object):
    """Preference data structure for the KeepNote application"""
    
    def __init__(self, pref_dir=None):

        if pref_dir is None:
            self._pref_dir = get_user_pref_dir()
        else:
            self._pref_dir = pref_dir

        self._set_data()

        '''
        # external apps
        self.external_apps = []
        self._external_apps_lookup = {}

        self.id = None

        # extensions
        self.disabled_extensions = []

        # window presentation options
        self.window_size = DEFAULT_WINDOW_SIZE
        self.window_maximized = True
        self.vsash_pos = DEFAULT_VSASH_POS
        self.hsash_pos = DEFAULT_HSASH_POS
        self.view_mode = DEFAULT_VIEW_MODE
        
        # look and feel
        self.treeview_lines = True
        self.listview_rules = True
        self.use_stock_icons = False
        self.use_minitoolbar = False

        # autosave
        self.autosave = True
        self.autosave_time = DEFAULT_AUTOSAVE_TIME
        
        self.default_notebook = ""
        self.use_last_notebook = True
        self.timestamp_formats = dict(keepnote.timestamp.DEFAULT_TIMESTAMP_FORMATS)
        self.spell_check = True
        self.image_size_snap = True
        self.image_size_snap_amount = 50
        self.use_systray = True
        self.skip_taskbar = False
        self.recent_notebooks = []

        self.language = ""


        '''
        
        # TODO: refactor these away
        # dialog chooser paths
        docs = get_user_documents()
        self.new_notebook_path = docs
        self.archive_notebook_path = docs
        self.insert_image_path = docs
        self.save_image_path = docs
        self.attach_file_path = docs
        
        
        # listener
        self.changed = Listeners()
        self.changed.add(self._on_changed)



    def get_pref_dir(self):
        """Returns preference directory"""
        return self._pref_dir


    def _on_changed(self):
        """Listener for preference changes"""
        self.write()

    
    def get_external_app(self, key):
        """Return an external application by its key name"""
        app = self._external_apps_lookup.get(key, None)
        if app == "":
            app = None
        return app

    
    #=========================================
    # Input/Output

    def _get_data(self, data=None):

        if data is None:
            data = orderdict.OrderDict()

        
        data["id"] = self.id

        # language
        data["language"] = self.language

        # autosave
        data["autosave"] = self.autosave
        data["autosave_time"] = self.autosave_time
        
        data["default_notebook"] = self.default_notebook
        data["use_last_notebook"] = self.use_last_notebook
        data["recent_notebooks"] = self.recent_notebooks
        data["timestamp_formats"] = self.timestamp_formats

        # window presentation options
        data["window"] = {"window_size": self.window_size,
                          "window_maximized": self.window_maximized,
                          "use_systray": self.use_systray,
                          "skip_taskbar": self.skip_taskbar
                          }

        # editor
        data["editors"] = {
            "general": {
                "spell_check": self.spell_check,
                "image_size_snap": self.image_size_snap,
                "image_size_snap_amount": self.image_size_snap_amount
                }
            }
        

        # viewer
        data["viewers"] = {
            "three_pane_viewer": {
                "vsash_pos": self.vsash_pos,
                "hsash_pos": self.hsash_pos,
                "view_mode": self.view_mode
                }
            }
        
        # look and feel
        data["look_and_feel"] = {
            "treeview_lines": self.treeview_lines,
            "listview_rules": self.listview_rules,
            "use_stock_icons": self.use_stock_icons,
            "use_minitoolbar": self.use_minitoolbar
            }

        # dialog chooser paths
        data["default_paths"] = self.default_paths

        # external apps
        data["external_apps"] = [
            {"key": app.key,
             "title": app.title,
             "prog": app.prog,
             "args": app.args}
            for app in self.external_apps]

        # extensions
        data["extension_info"] = {
            "disabled": self.disabled_extensions
            }
        data["extensions"] = {}


        return data


    def _set_data(self, data={}):

        self.id = data.get("id", None)
        
        # language
        self.language = data.get("language", "")

        # autosave
        self.autosave = data.get("autosave", True)
        self.autosave_time = data.get("autosave_time", DEFAULT_AUTOSAVE_TIME)
        self.timestamp_formats = data.get("timestamp_formats",
                         dict(keepnote.timestamp.DEFAULT_TIMESTAMP_FORMATS))

        # notebook
        self.default_notebook = data.get("default_notebook", "")
        self.use_last_notebook = data.get("use_last_notebook", True)
        self.recent_notebooks = data.get("recent_notebooks", [])[:]

        # window presentation options
        win = data.get("window", {})
        self.window_size = win.get("window_size", DEFAULT_WINDOW_SIZE)
        self.window_maximized = win.get("window_maximized", True)
        self.use_systray = win.get("use_systray", True)
        self.skip_taskbar = win.get("skip_taskbar", False)


        # three pane viewer options
        v = data.get("viewers", {}).get("three_pane_viewer", {})
        self.vsash_pos = v.get("vsash_pos", DEFAULT_VSASH_POS)
        self.hsash_pos = v.get("hsash_pos", DEFAULT_HSASH_POS)
        self.view_mode = v.get("view_mode", DEFAULT_VIEW_MODE)

        e = data.get("editors", {}).get("general", {})
        self.spell_check = e.get("spell_check", True)
        self.image_size_snap = e.get("image_size_snap", True)
        self.image_size_snap_amount = e.get("image_size_snap_amount", 50)

        
        # look and feel
        l = data.get("lookup_and_feel", {})
        self.treeview_lines = l.get("treeview_lines", True)
        self.listview_rules = l.get("listview_rules", True)
        self.use_stock_icons = l.get("use_sttock_icons", False)
        self.use_minitoolbar = l.get("use_minitoolbar", False)



        # dialog chooser paths
        doc = get_user_documents()
        self.default_paths = data.get("default_paths", {
            "new_notebook_path": doc,
            "archive_notebook_path": doc,
            "insert_image_path": doc,
            "save_image_path": doc,
            "attach_file_path": doc
            })

        self.disabled_extensions = data.get("extension_info", 
                                            {}).get("disabled", [])

        # external apps
        self.external_apps = []
        for app in data.get("external_apps", []):
            if "key" not in app:
                continue
            app2 = ExternalApp(app["key"], 
                               app.get("title", ""), 
                               app.get("prog", ""), 
                               app.get("args", ""))
            self.external_apps.append(app2)


        self._post_process_data()

    
    def _post_process_data(self):
        
        # setup id
        if self.id is None:
            self.id = str(uuid.uuid4())
        
        # make lookup
        self._external_apps_lookup = {}
        for app in self.external_apps:
            self._external_apps_lookup[app.key] = app

        # add default programs
        lst = get_external_app_defaults()
        for defapp in lst:
            if defapp.key not in self._external_apps_lookup:
                self.external_apps.append(defapp)
                self._external_apps_lookup[defapp.key] = defapp

        # place default apps first
        lookup = dict((x.key, i) for i, x in enumerate(DEFAULT_EXTERNAL_APPS))
        top = len(DEFAULT_EXTERNAL_APPS)
        self.external_apps.sort(key=lambda x: (lookup.get(x.key, top), x.key))
    

    def read(self):
        """Read preferences from file"""

        # ensure preference file exists
        if not os.path.exists(get_user_pref_file(self._pref_dir)):
            # write default
            try:
                init_user_pref_dir(self._pref_dir)
                self.write()
            except Exception, e:
                raise KeepNotePreferenceError("Cannot initialize preferences", e)
        

        try:
            # read preferences xml
            tree = ET.ElementTree(
                file=get_user_pref_file(self._pref_dir))
            
            # parse xml
            # check tree structure matches current version
            root = tree.getroot()
            if root.tag == "keepnote":
                p = root.find("pref")
                if not p:
                    # convert from old preference version
                    import keepnote.compat.pref as old
                    old_pref = old.KeepNotePreferences()
                    old_pref.read(get_user_pref_file(self._pref_dir))
                    data = old_pref._get_data()
                else:
                    # get data object from xml
                    d = p.find("dict")
                    if d:
                        data = plist.load_etree(d)
                    else:
                        data = orderdict.OrderDict()

                # set data
                self._set_data(data)
        except Exception, e:
            raise KeepNotePreferenceError("Cannot read preferences", e)
        
                
        # notify listeners
        self.changed.notify()

 
    def write(self):
        """Write preferences to file"""        

        try:
            if not os.path.exists(self._pref_dir):
                init_user_pref_dir(self._pref_dir)
            
            #out = sys.stdout
            out = safefile.open(get_user_pref_file(self._pref_dir), "w", 
                                codec="utf-8")
            out.write(u'<?xml version="1.0" encoding="UTF-8"?>\n'
                      u'<keepnote>\n'
                      u'<pref>\n')
            plist.dump(self._get_data(), out, indent=4, depth=4)
            out.write(u'</pref>\n'
                      u'</keepnote>')
            
            out.close()
                                         
        except (IOError, OSError), e:
            log_error(e, sys.exc_info()[2])
            raise NoteBookError(_("Cannot save preferences"), e)



#=============================================================================
# Application class

        
class KeepNoteError (StandardError):
    def __init__(self, msg, error=None):
        StandardError.__init__(self, msg)
        self.msg = msg
        self.error = error
    
    def __repr__(self):
        if self.error:
            return str(self.error) + "\n" + self.msg
        else:
            return self.msg

    def __str__(self):
        return self.msg


class ExtensionEntry (object):
    """An entry for an Extension in the KeepNote application"""

    def __init__(self, filename, ext_type, ext):
        self.filename = filename
        self.ext_type = ext_type
        self.ext = ext

    def get_key(self):
        return os.path.basename(self.filename)


class KeepNote (object):
    """KeepNote application class"""

    
    def __init__(self, basedir=None):

        # base directory of keepnote library
        if basedir is not None:
            set_basedir(basedir)
        self._basedir = BASEDIR
        
        # load application preferences
        self.pref = KeepNotePreferences()

        # list of possible application commands
        self._commands = {}

        # list of application notebooks
        self._notebooks = {}
        self._notebook_count = {}
        
        # set of registered extensions for this application
        self._extensions = {}

        self.pref.changed.add(self.load_preferences)


    def init(self):
        """Initialize from preferences saved on disk"""
        
        # read preferences
        self.pref.read()
        self.set_lang()
        
        # scan extensions
        self.clear_extensions()
        self.scan_extensions_dir(get_system_extensions_dir(), "system")
        self.scan_extensions_dir(get_user_extensions_dir(), "user")

        # initialize all extensions
        self.init_extensions()


    def load_preferences(self):
        """Load information from preferences"""
        pass


    def save_preferneces(self):
        """TODO: not used yet"""
        pass

        #self._app.pref.write()

    def set_lang(self):                
        """Set the language based on preference"""

        keepnote.trans.set_lang(self.pref.language)


    #==================================
    # actions

    def open_notebook(self, filename, window=None, task=None):
        """Open a new notebook"""
        
        notebook = keepnote.notebook.NoteBook()
        notebook.load(filename)
        return notebook

    def close_notebook(self, notebook):
        """Close notebook"""

        if self.has_ref_notebook(notebook):
            self.unref_notebook(notebook)


    def get_notebook(self, filename, window=None, task=None):
        """
        Returns a an opened notebook referenced by filename
        
        Open a new notebook if it is not already opened.
        """

        filename = os.path.realpath(filename)
        if filename not in self._notebooks:
            notebook = self.open_notebook(filename, window, task=task)
            if notebook is None:
                return None
            self._notebooks[filename] = notebook
            self.ref_notebook(notebook)
        else:
            notebook = self._notebooks[filename]
            self.ref_notebook(notebook)
            
        return notebook


    def ref_notebook(self, notebook):
        if notebook not in self._notebook_count:
            self._notebook_count[notebook] = 1
        else:
            self._notebook_count[notebook] += 1


    def unref_notebook(self, notebook):
        self._notebook_count[notebook] -= 1 

        # close if refcount is zero
        if self._notebook_count[notebook] == 0:
            del self._notebook_count[notebook]

            for key, val in self._notebooks.iteritems():
                if val == notebook:
                    del self._notebooks[key]
                    break

            notebook.close()

    def has_ref_notebook(self, notebook):
        return notebook in self._notebook_count


    def iter_notebooks(self):
        """Iterate through open notebooks"""
        
        return self._notebooks.itervalues()

    
    def run_external_app(self, app_key, filename, wait=False):
        """Runs a registered external application on a file"""

        app = self.pref.get_external_app(app_key)
        
        if app is None or app.prog == "":
            if app:
                raise KeepNoteError(_("Must specify '%s' program in Helper Applications" % app.title))
            else:
                raise KeepNoteError(_("Must specify '%s' program in Helper Applications" % app_key))

        # build command arguments
        cmd = [app.prog] + app.args
        if "%s" not in cmd:
            cmd.append(filename)
        else:
            for i in xrange(len(cmd)):
                if cmd[i] == "%s":
                    cmd[i] = filename
        
        # create proper encoding
        cmd = map(lambda x: unicode(x), cmd)
        if get_platform() == "windows":
            cmd = [x.encode('mbcs') for x in cmd]
        
        # execute command
        try:
            proc = subprocess.Popen(cmd)
        except OSError, e:
            raise KeepNoteError(
                _(u"Error occurred while opening file with %s.\n\n" 
                  u"program: '%s'\n\n"
                  u"file: '%s'\n\n"
                  u"error: %s")
                % (app.title, app.prog, filename, unicode(e)), e)

        # wait for process to return
        # TODO: perform waiting in gtk loop
        # NOTE: I do not wait for any program yet
        if wait:
            return proc.wait()


    def open_webpage(self, url):
        """View a node with an external web browser"""

        if url:
            self.run_external_app("web_browser", url)
          

    def take_screenshot(self, filename):
        """Take a screenshot and save it to 'filename'"""

        # make sure filename is unicode
        filename = ensure_unicode(filename, "utf-8")

        if get_platform() == "windows":
            # use win32api to take screenshot
            # create temp file
            
            f, imgfile = tempfile.mkstemp(u".bmp", filename)
            os.close(f)
            mswin.screenshot.take_screenshot(imgfile)
        else:
            # use external app for screen shot
            screenshot = self.pref.get_external_app("screen_shot")
            if screenshot is None or screenshot.prog == "":
                raise Exception(_("You must specify a Screen Shot program in Application Options"))

            # create temp file
            f, imgfile = tempfile.mkstemp(".png", filename)
            os.close(f)

            proc = subprocess.Popen([screenshot.prog, imgfile])
            if proc.wait() != 0:
                raise OSError("Exited with error")

        if not os.path.exists(imgfile):
            # catch error if image is not created
            raise Exception(_("The screenshot program did not create the necessary image file '%s'") % imgfile)

        return imgfile  


    def error(self, text, error=None, tracebk=None):
        """Display an error message"""

        keepnote.log_message(text)
        if error is not None:
            keepnote.log_error(error, tracebk)


    def quit(self):
        pass

    #================================
    # commands

    def get_command(self, command_name):

        return self._commands.get(command_name, None)

    def get_commands(self):
        return self._commands.values()


    def add_command(self, command):

        if command.name in self._commands:
            raise Exception(_("command '%s' already exists") % command.name)

        self._commands[command.name] = command

    def remove_command(self, command_name):
        
        if command_name in self._commands:
            del self._commands[command_name]


    #================================
    # extensions


    def clear_extensions(self):
        """Disable and unregister all extensions for the app"""

        # disable all enabled extensions
        for ext in self.iter_extensions(enabled=True):
            ext.disable()

        # reset registered extensions list
        self._extensions = {
            "keepnote": ExtensionEntry("", "system", KeepNoteExtension(self))}


    def add_extension_entry(self, filename, ext_type):
        """Add an extension filename to the app's extension entries"""
        
        entry = ExtensionEntry(filename, ext_type, None)
        self._extensions[entry.get_key()] = entry
        return entry
                

    def remove_extension_entry(self, ext_key):
        """Remove an extension entry"""
        
       # retrieve information about extension
        entry = self._extensions.get(ext_key, None)
        if entry:
            if entry.ext:
                # disable extension
                ext.enable(False)

            # unregister extension from app
            del self._extensions[ext_key]


    def scan_extensions_dir(self, extensions_dir, ext_type):
        """Scan extensions directory and register extensions with app"""
        
        for filename in extension.iter_extensions(extensions_dir):
            self.add_extension_entry(filename, ext_type)
        
        
    def init_extensions(self):
        """Enable all registered extensions"""
        
        # ensure all extensions are imported first
        for ext in self.iter_extensions():
            pass

        # enable those extensions that have their dependencies met
        for ext in self.iter_extensions():
            # enable extension
            try:
                if ext.key not in self.pref.disabled_extensions:
                    log_message(_("enabling extension '%s'\n") % ext.key)
                    enabled = ext.enable(True)

            except extension.DependencyError, e:

                log_message(_("  skipping extension '%s':\n") % ext.key)
                for dep in ext.get_depends():
                    if not self.dependency_satisfied(dep):
                        log_message(_("    failed dependency: %s\n") % repr(dep))

            except Exception, e:
                log_error(e, sys.exc_info()[2])
    
    
    def get_extension(self, name):
        """Get an extension module by name"""
        
        # return None if extension name is unknown
        if name not in self._extensions:
            return None

        # get extension information
        entry = self._extensions[name]

        # load if first use
        if entry.ext is None:
            try:
                entry.ext = extension.import_extension(self, name, entry.filename)
                entry.ext.type = entry.ext_type
                entry.ext.enabled.add(
                    lambda e: self.on_extension_enabled(entry.ext, e))

            except KeepNotePreferenceError, e:
                log_error(e, sys.exc_info()[2])
                
        return entry.ext


    def iter_extensions(self, enabled=False):
        """
        Iterate through all extensions

        If 'enabled' is True, then only enabled extensions are returned.
        """

        for name in self._extensions:
            ext = self.get_extension(name)
            if ext and (ext.is_enabled() or not enabled):
                yield ext


    def dependency_satisfied(self, dep):
        """Returns True if dependency 'dep' is satisfied by registered extensions"""

        ext  = self.get_extension(dep[0])
        return extension.dependency_satisfied(ext, dep)


    def dependencies_satisfied(self, depends):
        """Returns True if dependencies 'depends' are satisfied"""

        for dep in depends:
            if not extension.dependency_satisfied(self.get_extension(dep[0]), 
                                                  dep):
                return False
        return True


    def on_extension_enabled(self, ext, enabled):
        """Callback for when extension is enabled"""

        # update user preference on which extensions are disabled
        if enabled:
            if ext.key in self.pref.disabled_extensions:
                self.pref.disabled_extensions.remove(ext.key)
        else:
            if ext.key not in self.pref.disabled_extensions:
                self.pref.disabled_extensions.append(ext.key)
    

    def install_extension(self, filename):
        """Install a new extension from package 'filename'"""

        userdir = get_user_extensions_dir()

        newfiles = []
        try:
            # unzip and record new files
            for fn in unzip(filename, userdir):
                newfiles.append(fn)

            # rescan user extensions
            exts = set(self._extensions.keys())
            self.scan_extensions_dir(userdir, "user")

            # find new extensions
            new_names = set(self._extensions.keys()) - exts
            new_exts = [self.get_extension(name) for name in new_names]

        except Exception, e:
            self.error(_("Unable to install extension '%s'") % filename,
                       e, tracebk=sys.exc_info()[2])

            # delete newfiles
            for fn in newfiles:
                try:
                    keepnote.log_message(_("removing '%s'") % newfile)
                    os.remove(newfile)
                except:
                    # delete may fail, continue
                    pass

            return []
        
        # enable new extensions
        log_message(_("Enabling new extensions:\n"))
        for ext in new_exts:
            log_message(_("enabling extension '%s'\n") % ext.key)
            ext.enable(True)

        return new_exts


    def uninstall_extension(self, ext_key):
        """Uninstall an extension"""

        # retrieve information about extension
        entry = self._extensions.get(ext_key, None)

        if entry is None:            
            self.error(_("Unable to uninstall unknown extension '%s'.") % ext.key)
            return False

        # cannot uninstall system extensions
        if entry.ext_type != "user":
            self.error(_("KeepNote can only uninstall user extensions"))
            return False

        # if extension is imported, make sure it is disabled, unregistered
        ext = entry.ext
        if ext:
            # disable extension
            ext.enable(False)

            # unregister extension from app
            del self._extensions[ext.key]


        # delete extension from filesystem
        try:      
            shutil.rmtree(entry.filename)
        except OSError, e:
            self.error(_("Unable to uninstall extension.  Do not have permission."))
            return False

        return True


    def can_uninstall(self, ext):
        """Return True if extension can be uninstalled"""
        return ext.type != "system"
        

    def get_extension_base_dir(self, extkey):
        """Get base directory of an extension"""
        return self._extensions[extkey].filename

    
    def get_extension_data_dir(self, extkey):
        """Get the data directory of an extension"""
        return os.path.join(get_user_extensions_data_dir(), extkey)




def unzip(filename, outdir):
    """Unzip an extension"""

    extzip = zipfile.ZipFile(filename)
            
    for fn in extzip.namelist():
        if fn.endswith("/") or fn.endswith("\\"):
            # skip directory entries
            continue

        # quick test for unusual filenames
        if fn.startswith("../") or "/../" in fn:
            raise Exception("bad file paths in zipfile '%s'" % fn)

        # determine extracted filename
        newfilename = os.path.join(outdir, fn)

        # ensure directory exists
        dirname = os.path.dirname(newfilename)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        elif not os.path.isdir(dirname) or os.path.exists(newfilename):
            raise Exception("Cannot unzip.  Other files are in the way")


        # extract file
        out = open(newfilename, "wb")
        out.write(extzip.read(fn))
        out.flush()
        out.close()

        yield newfilename


class KeepNoteExtension (extension.Extension):
    """Extension that represents the application itself"""

    version = PROGRAM_VERSION
    key = "keepnote"
    name = "KeepNote"
    description = "The KeepNote application"
    visible = False

    def __init__(self, app):
        extension.Extension.__init__(self, app)
        

    def enable(self, enable):
        """This extension is always enabled"""
        extension.Extension.enable(self, True)
        return True

    def get_depends(self):
        """Application has no dependencies, returns []"""
        return []

