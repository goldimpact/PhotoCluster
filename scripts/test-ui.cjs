/* Explicit files work across Node versions and Windows/POSIX shells; exclude data/. */
const {readdirSync}=require('node:fs');
const {spawnSync}=require('node:child_process');
const {resolve,join}=require('node:path');
const root=resolve(__dirname,'..');
const files=readdirSync(join(root,'tests')).filter(file=>file.endsWith('.test.cjs')).sort().map(file=>join('tests',file));
if(!files.length)throw Error('No UI tests found');
const result=spawnSync(process.execPath,['--test',...files],{cwd:root,stdio:'inherit'});
if(result.error)throw result.error;
process.exitCode=result.status??1;
