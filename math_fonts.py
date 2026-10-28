"""Inspect SFNT table directories without assuming ordinary fonts support Word math."""
import struct
from pathlib import Path

def inspect_font_file(path):
    try:
        with Path(path).open('rb') as f:
            header=f.read(12)
            if len(header)!=12 or header[:4] not in (b'OTTO',b'\x00\x01\x00\x00',b'true'):return 'unknown'
            count=struct.unpack('>H',header[4:6])[0]
            if count<1 or count>4096:return 'unknown'
            tables=f.read(count*16)
            if len(tables)!=count*16:return 'unknown'
            return 'math' if any(tables[i:i+4]==b'MATH' for i in range(0,len(tables),16)) else 'ordinary'
    except (OSError,ValueError,struct.error):return 'unknown'

def font_assessment(name,catalog):
    names={n.casefold():n for n in catalog.get('installedFonts',[])}
    key=names.get(name.casefold())
    detection=catalog.get('detection',{}).get('status','detected')
    status=catalog.get('mathFontStatus',{}).get(key,'unknown') if key else ('not_detected' if detection=='detected' else 'unknown')
    return {'font':name,'status':status,'wordVerified':False}
