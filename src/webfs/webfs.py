#!/usr/bin/env python

"""
    A scraper that thinks it's a filesystem.
"""

__all__ = [
    'URL',
    'Page',
    'Dir',
    'File',
    'get_cache',
    'get_cache_root',
    'set_cache_root',
]

# stdlib
import io
import os
import re
import sys
import json
import functools
from urllib.parse import urljoin, urlparse

# dependencies
import bs4
import mmry
import kern
import requests
import colorama

class URL(str):
    """
    A str subclass which also implements
    RFC 1808 definition of relative urls
    https://www.ietf.org/rfc/rfc1808.txt
    """
    def __new__(cls, url):
        self = super().__new__(cls, url)
        # RFC 1808: defines the fields in a relative url as
        # <scheme>://<net_loc>/<path>;<params>?<query>#<fragment>
        parsed = urlparse(url)
        for key in ('scheme', 'netloc', 'path', 'params', 'query', 'fragment'):
            setattr(self, key, getattr(parsed, key))
        return self

    def hostname(self):
        return self.netloc

    def abspath(self, arg):
        """ resolve arbitrary hrefs relative to the current url """
        arg = self.unwrap(arg)
        url = urljoin(self, arg)
        return url

    @classmethod
    def wrap(cls, arg):
        if isinstance(arg, cls):
            return arg
        return cls(arg)

    @classmethod
    def unwrap(cls, arg):
        while isinstance(arg, cls):
            arg = arg.url
        return arg


class Page:

    def __init__(self, url):
        self.url = URL(url)

    def open(self):
        import webbrowser
        webbrowser.open(self.url)

    @functools.lru_cache(maxsize=1024)
    def bytes(self):
        url = self.url
        cache = get_cache('html')
        try:
            page = cache.load_blob(url)
        except:
            page = self.fetch()
            cache.save_blob(url, page)
        return page

    def page(self):
        return self.bytes().decode()

    @functools.lru_cache(maxsize=1024)
    def soup(self):
        return bs4.BeautifulSoup(self.page(), 'html.parser')

    def fetch(self):
        HEADERS = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                                  'Chrome/111.0.0.0 Safari/537.36')}
        return requests.get(self.url, headers=HEADERS).content

    def __repr__(self):
        return f"{self.__class__.__name__}({self.url!r})"

    def abspath(self, href):
        return self.url.abspath(href)

    def __repr__(self):
        return self._repr(f"{self.__class__.__name__}({self.url!r})")

    def _repr(self, string):
        try:
            color = self._color
            reset = colorama.Fore.RESET
            return f"{color}{string}{reset}"
        except:
            return string

    _color = colorama.Fore.LIGHTWHITE_EX


class Dir(Page):

    """
        A webpage that acts like a directory.
        We don't care about the content itself, except
        insofar as that content points to other pages.
    """

    def list_links(self):
        soup = self.soup()
        elems = soup.find_all('a')
        urls = []
        for elem in elems:
            if (href := elem.get('href')) is None:
                continue
            if re.search('[.](jpg|png|webm)$', href):
                continue
            url = self.abspath(href)
            url = NavigableString(url, elem)
            urls.append(url)
        urls = sorted(set(urls))
        return urls

    def list_images(self):
        soup = self.soup()
        elems = soup.find_all('img')
        urls = []
        for elem in elems:
            if (src := elem.get('src')) is None:
                continue
            url = self.abspath(src)
            url = NavigableString(url, elem)
            urls.append(url)
        urls = sorted(set(urls))
        return urls

    def define_dirs(self):
        return [Dir(url) for url in self.list_links()]

    def define_files(self):
        return [File(url) for url in self.list_images()]

    def prefetch(self):
        futs = []
        from concurrent.futures import ThreadPoolExecutor, as_completed
        items = self.ls()
        with ThreadPoolExecutor(max_workers=2*os.cpu_count()) as executor:
            for item in items:
                fut = executor.submit(item.page)
                futs.append(fut)
            for fut in as_completed(futs):
                # we don't want the result since, it's cached
                # just make sure we have it
                fut.result()
        return items

    @functools.lru_cache(maxsize=1024)
    def ls(self):
        """ https://www.halolinux.us/kernel-reference/the-dentry-cache.html """
        dirs  = self.define_dirs()
        files = self.define_files()
        return List(dirs + files)

    _color = colorama.Fore.LIGHTBLUE_EX


class File(Page):

    def text(self):
        return self.soup().text

    def cat(self):
        return self.bytes()

    def image_to_text(self):
        return kern.image.to_text(io.BytesIO(self.cat()))

    def pdf_to_text(self):
        return kern.pdf.to_text(io.BytesIO(self.cat()))

    _color = colorama.Fore.LIGHTYELLOW_EX


class NavigableString(str):
    def __new__(cls, object, elem):
        string = super().__new__(cls, object)
        string.elem = elem
        return string


def match(regex, string, context=0, **kwds):
    if context == 0:
       return re.search(regex, string, **kwds)
    if not hasattr(string, 'elem'):
        raise ValueError(f"Not navigable: {string!r}")
    elem = string.elem
    while context > 0:
        elem = elem.parent
        context -= 1
    string = str(elem)
    return re.search(regex, string, **kwds)


class List(list):

    def grep(self, regex, r=False, i=False, C=0):
        cls = type(self)
        context = C
        recursive = r
        kwds = {'flags': re.I} if i else {}
        if not recursive and not context:
            return cls([o for o in self if match(regex, o.url, **kwds)])
        if context and not recursive:
            return cls([o for o in self if match(regex, o.url, context=context, **kwds)])
        if recursive and not context:
            prefetch(self)
            return cls([o for o in self if match(regex, o.page(), **kwds)])
        raise ValueError(f"Bad grep options: {regex!r}, recursive={recursive}, context={context}")

    def dirs(self):
        cls = type(self)
        return cls([o for o in self if isinstance(o, Dir)])

    def files(self):
        cls = type(self)
        return cls([o for o in self if isinstance(o, File)])

    def __getattr__(self, attr):
        if len(self) == 1:
            return getattr(self[0], attr)
        raise AttributeError(attr)

    def __getitem__(self, item):
        o = super().__getitem__(item)
        if isinstance(o, list):
            cls = type(self)
            return cls(o)
        else:
            return o


# TODO: make these belong to a top level FS class
FS = {
    'cache_root': None,
    'caches': {},
}
def get_cache_root():
    return FS['cache_root']

def set_cache_root(dir):
    FS['cache_root'] = dir

def get_cache(name):
    try:
        return FS[name]
    except:
        FS[name] = mmry.Cache(name, root=get_cache_root())
        return FS[name]
