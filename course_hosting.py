"""Explicit opt-in configuration for the Lingnan course deployment."""
from dataclasses import dataclass
from urllib.parse import urlsplit

@dataclass(frozen=True)
class Config:
    enabled: bool
    host: str = '127.0.0.1'
    port: int = 8770
    data_dir: str = ''
    origin: str = ''
    def allowed(self, host, origin):
        if not self.enabled:
            hosts={f'127.0.0.1:{self.port}',f'localhost:{self.port}'}
            return host in hosts and (not origin or origin in {'http://'+h for h in hosts})
        public=urlsplit(self.origin)
        allowed_hosts={public.netloc,f'127.0.0.1:{self.port}',f'localhost:{self.port}'}
        return host in allowed_hosts and (not origin or origin==self.origin)

def config(env):
    if env.get('DOCSTYLE_COURSE_MODE')!='1': return Config(False)
    port=int(env.get('PORT','8000'))
    if not 1<=port<=65535:raise ValueError('PORT 无效')
    origin=env.get('DOCSTYLE_PUBLIC_ORIGIN','https://mf01.show.lingnan.top').rstrip('/')
    p=urlsplit(origin)
    if p.scheme!='https' or p.hostname!='mf01.show.lingnan.top' or p.path or p.query or p.fragment or p.username or p.password or p.port:raise ValueError('课程站点来源配置无效')
    return Config(True,'0.0.0.0',port,env.get('DATA_DIR','/data'),origin)
