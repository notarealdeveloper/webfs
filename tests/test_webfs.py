import webfs

def test_ls():
    root = webfs.Dir('https://www.gentoo.org/downloads/mirrors/')
    list = root.ls()
    pages = [e for e in list if e.url == 'https://gentoo.osuosl.org/']
    assert len(pages) == 1
