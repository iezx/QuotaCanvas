"""Fingerprint local web assets so old browser/CDN copies cannot mask an upgrade."""
import hashlib
from pathlib import Path
import re
from urllib.parse import urlsplit


def prepare(root):
    root=Path(root)
    for page in root.glob('*.html'):
        original=page.read_text(encoding='utf-8')
        def tag(match):
            def attribute(attr):
                url=attr.group(2);path=urlsplit(url).path
                if not path.startswith('/') or Path(path).suffix not in ('.js','.css'):
                    return attr.group(0)
                source=root/path.lstrip('/')
                if not source.is_file():
                    raise ValueError('Missing web asset: '+path)
                version=hashlib.sha256(source.read_bytes()).hexdigest()[:12]
                return attr.group(1)+path+'?v='+version+attr.group(3)
            return re.sub(r'''((?:src|href)=["'])([^"']+)(["'])''',attribute,match.group(0))
        updated=re.sub(r'<(?:script|link)\b[^>]*>',tag,original,flags=re.I)
        if updated!=original:
            temporary=page.with_suffix('.html.tmp')
            temporary.write_text(updated,encoding='utf-8')
            temporary.replace(page)


if __name__=='__main__':
    prepare(Path(__file__).resolve().parent/'web')
