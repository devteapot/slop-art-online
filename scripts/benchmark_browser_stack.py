#!/usr/bin/env python3
"""Actual Bevy observer + controller workload, gated after browser enrollment.

Fresh isolated services and Chrome profile per run. Retains the real canvas,
console, rAF intervals and exact host/browser assets. No inference or input-to-
photon claim. The controller-boundary driver owns database shutdown and exports.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--scenario', type=Path, required=True)
    p.add_argument('--image', required=True)
    p.add_argument('--hz', type=int, choices=[30, 60], required=True)
    p.add_argument('--seconds', type=int, default=60)
    p.add_argument('--implementation', type=Path, help='replay the frozen authority/probe from the paired run')
    p.add_argument('--agent-browser', type=Path, required=True)
    p.add_argument('--chrome', type=Path, required=True)
    args = p.parse_args()
    out = args.output.resolve()
    if out.exists(): raise ValueError('output must be fresh')
    # Chromium puts a Unix-domain socket below TMPDIR (108-byte path limit).
    # Keep this short even when the descriptive experiment label is long.
    temp = ROOT/'.local/t'/hashlib.sha256(str(out).encode()).hexdigest()[:8]
    temp.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, TMPDIR=str(temp))
    gate = out/'start.gate'
    command = ['python3', str(ROOT/'scripts/benchmark_controller_boundary.py'),
        '--scenario', str(args.scenario.resolve()), '--output', str(out),
        '--image', args.image, '--seconds', str(args.seconds), '--action-hz', str(args.hz),
        '--physical-clock', '--human-actor', '3', '--direct-input', '--verify-render-parts', '--start-gate', str(gate)]
    if args.implementation: command.extend(['--implementation',str(args.implementation.resolve())])
    processes = []
    logs = []
    def spawn(command, name, process_env=env):
        log = (out/name).open('w'); logs.append(log)
        process = subprocess.Popen(command, cwd=ROOT, env=process_env, stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
        return process
    def wait_file(path, timeout, process):
        until = time.monotonic()+timeout
        while not path.exists():
            if process.poll() is not None: raise RuntimeError(f'process exited {process.returncode} before {path.name}')
            if time.monotonic()>until: raise TimeoutError(path.name)
            time.sleep(.2)
    def browser(*command):
        return subprocess.check_output([str(args.agent_browser), '--cdp', '9227', *command],
            cwd=ROOT, env=env, text=True, stderr=subprocess.STDOUT, timeout=45)
    # The child creates the immutable output directory itself.
    driver_log = out.parent/(out.name+'-driver.log')
    driver_log.parent.mkdir(parents=True, exist_ok=True)
    with driver_log.open('w') as log:
        runner = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            wait_file(out/'config.json', 90, runner)
            config = json.loads((out/'config.json').read_text())
            resume = dict(db=config['database'], run=config['run'],
                controller_database=config['controller_database'], controller_server=config['controller_server'],
                deadline_clock=True, archive_audit=True)
            (out/'resume.json').write_text(json.dumps(resume))
            # Do not race world creation. Enrollment begins only after creation.
            until = time.monotonic()+120
            while 'enrolled ' not in (out/'probe.log').read_text():
                if runner.poll() is not None: raise RuntimeError('workload failed during creation')
                if time.monotonic()>until: raise TimeoutError('world enrollment')
                time.sleep(.2)
            host_env = dict(env, BEVY_DEV_RESUME_ACTIVE=str(out/'resume.json'),
                BEVY_DEV_SERVER=config['server'], BEVY_DEV_PORT='18929',
                BEVY_DEV_OUTPUT=str(out/'host'), BEVY_DEV_ARCHIVE_ONLY='1',
                SPACETIME_CONFIG_PATH=config['cli_config'], SPACETIME_CONTROL_CLI=config['cli'])
            host = spawn([str(ROOT/'target/release/sao-dev-client')], 'host.log', host_env)
            profile = ROOT/'.local/credentials'/('browser-'+out.name)
            chrome_command = [str(args.chrome), '--enable-gpu', '--use-angle=vulkan',
                '--enable-features=Vulkan', '--disable-vulkan-surface', '--enable-unsafe-webgpu',
                '--ignore-gpu-blocklist', '--headless', '--no-sandbox', '--disable-dev-shm-usage',
                '--remote-debugging-port=9227', '--user-data-dir='+str(profile), '--window-size=1440,900', 'about:blank']
            chrome=spawn(chrome_command, 'chrome.log')
            time.sleep(2)
            if chrome.poll() is not None: raise RuntimeError(f'Chrome startup failed: {chrome.returncode}; see chrome.log')
            (out/'browser-open.txt').write_text(browser('open', 'http://127.0.0.1:18929'))
            browser('console', '--clear')
            browser('errors', '--clear')
            wait_file(out/'ready.json', 180, runner)
            time.sleep(3)
            # Exercise rich inspection and return to the declared closed-inspector
            # workload before collecting any timed samples.
            browser('press', 'i')
            time.sleep(2)
            browser('screenshot', str(out/'browser-inspector-open.png'))
            browser('press', 'i')
            time.sleep(2)
            (out/'browser-snapshot.txt').write_text(browser('snapshot', '-i'))
            browser('screenshot', str(out/'browser-initial.png'))
            assets = out/'browser-implementation'; assets.mkdir()
            shutil.copytree(ROOT/'client/dist-participant', assets/'dist-participant')
            shutil.copy2(ROOT/'target/release/sao-dev-client', assets/'sao-dev-client')
            shutil.copy2(Path(__file__), out/'browser-driver.py')
            hashes = {str(f.relative_to(assets)):hashlib.sha256(f.read_bytes()).hexdigest()
                for f in assets.rglob('*') if f.is_file()}
            (out/'browser-manifest.json').write_text(json.dumps(dict(files=hashes,chrome=chrome_command,
                workload_command=command,scope='rAF callbacks, not GPU presentation or input-to-photon'),indent=2))
            browser('eval', 'window.__frames={start:Date.now(),times:[],running:true}; let previous; '
                'function record(t){if(!window.__frames.running)return; if(previous!==undefined) '
                'window.__frames.times.push([Date.now(),t-previous]); previous=t; requestAnimationFrame(record);} '
                'requestAnimationFrame(record); "started"')
            gate.touch()
            runner.wait(timeout=args.seconds+180)
            (out/'browser-frames.json').write_text(browser('eval', 'window.__frames.running=false; JSON.stringify(window.__frames)'))
            browser('screenshot', str(out/'browser-final.png'))
            (out/'browser-errors.txt').write_text(browser('errors'))
            (out/'browser-console.txt').write_text(browser('console'))
            if runner.returncode: raise RuntimeError(f'driver exit {runner.returncode}')
            (out/'browser-result.json').write_text(json.dumps(dict(ok=True),indent=2))
        except Exception as error:
            if out.exists():
                (out/'browser-result.json').write_text(json.dumps(dict(ok=False,error=str(error),
                    detail=getattr(error,'output',None)),indent=2))
            raise
        finally:
            # Allow the boundary driver's own error/timeout path to retain evidence
            # and stop services; terminate our browser/host only after it exits.
            if runner.poll() is None:
                if out.exists() and not gate.exists(): gate.with_suffix('.cancel').touch()
                runner.wait(timeout=args.seconds+360)
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
            for log in logs: log.close()


if __name__ == '__main__': main()
