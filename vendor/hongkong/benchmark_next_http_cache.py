"""Prepare an explicitly recorded, byte-identical CIFAR download cache."""
import hashlib
import shlex

from agent_artifacts import upload_artifacts, verified_artifact
from benchmark_next_agent_runtime import prepare_runtime
from project_paths import inside

DIRECTORY = '/opt/benchmark-next-public-cache'
URL = 'http://www.cs.toronto.edu/~kriz/cifar-10-binary.tar.gz'


async def prepare_http_cache(root, environment, config):
    if (config['url'] != URL or config['md5'] != 'c32a1d4ab5d03f1284b67883e8d87530'
            or config['bytes'] != 170052171):
        raise ValueError('Only the verified official CIFAR binary archive is supported')
    path = inside(root, config['path'])
    artifact = verified_artifact(path, config['sha256'])
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'md5').hexdigest() != config['md5']:
            raise ValueError('Cache differs from the dataset publisher checksum')
    helper = verified_artifact(root / 'scripts/benchmark_http_cache.py', config['helper_sha256'])

    async def execute(command):
        result = await environment.exec(command=command, user='root', timeout_sec=120)
        if result.return_code:
            raise RuntimeError('Public cache preparation failed: ' + (result.stderr or '')[-500:])
        return result

    runtime = await prepare_runtime(root, environment, execute, 'public-cache')
    await upload_artifacts(root, {'cifar-10-binary.tar.gz': artifact, 'proxy.py': helper},
                           DIRECTORY, environment.upload_file, execute)
    args = [runtime['python'], DIRECTORY + '/proxy.py', '--file', DIRECTORY + '/cifar-10-binary.tar.gz',
            '--url', URL, '--sha256', config['sha256']]
    await execute('nohup ' + shlex.join(args) + ' > ' + DIRECTORY + '/proxy.log 2>&1 < /dev/null &')
    probe = '''import http.client,time
for attempt in range(30):
 try:
  conn=http.client.HTTPConnection('127.0.0.1',18080,timeout=2)
  conn.request('HEAD',%r)
  response=conn.getresponse()
  assert response.status==200 and int(response.getheader('Content-Length'))==170052171
  conn.close()
  break
 except OSError:
  if attempt==29:raise
  time.sleep(0.2)
''' % URL
    await execute(shlex.quote(runtime['python']) + ' -c ' + shlex.quote(probe))
    environment.logger.info('Verified public CIFAR HTTP cache: sha256=%s bytes=%s; official URL and response bytes unchanged',
                            config['sha256'], config['bytes'])
