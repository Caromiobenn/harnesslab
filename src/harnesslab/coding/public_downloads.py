"""Transport adapters for exact, checksum-pinned public dependency downloads."""

from __future__ import annotations


def wget_wrapper(python: str, real_wget: str, downloads: dict, log_path: str) -> str:
    """Serve cached ordinary wget downloads; forward unsupported invocations unchanged."""
    return f"""#!{python}
import hashlib,json,os,shutil,sys
from pathlib import Path
from urllib.parse import urlsplit
args=sys.argv[1:];downloads={downloads!r}
url=None;output=None;directory='.';index=0
def fallback():
    os.execv({real_wget!r},[{real_wget!r},*args])
while index<len(args):
    value=args[index]
    if value in ('-q','--quiet','-nv','--no-verbose','--no-check-certificate'):
        pass
    elif value in ('-O','--output-document','-P','--directory-prefix'):
        index+=1
        if index>=len(args):fallback()
        if value in ('-O','--output-document'):output=args[index]
        else:directory=args[index]
    elif value.startswith('--output-document='):
        output=value.split('=',1)[1]
    elif value in downloads and url is None:
        url=value
    else:fallback()
    index+=1
if url is None:fallback()
artifact=downloads[url];source=Path(artifact['path'])
with source.open('rb') as stream:
    if hashlib.file_digest(stream,'sha256').hexdigest()!=artifact['sha256']:
        raise RuntimeError('Cached public download checksum mismatch: '+url)
if output=='-':
    with source.open('rb') as stream:shutil.copyfileobj(stream,sys.stdout.buffer)
else:
    if output is None:
        Path(directory).mkdir(parents=True,exist_ok=True)
        target=Path(directory)/Path(urlsplit(url).path).name
        original=target;number=0
        while target.exists():
            number+=1;target=Path(str(original)+'.'+str(number))
    else:target=Path(output)
    shutil.copyfile(source,target)
with open({log_path!r},'a') as stream:
    stream.write(json.dumps({{'tool':'wget','url':url,'sha256':artifact['sha256']}})+chr(10))
"""
