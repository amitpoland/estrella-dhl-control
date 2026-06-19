// Syntax-check JSX files with @babel/parser (jsx plugin)
const parser = require(process.argv[2] + '/node_modules/@babel/parser');
const fs = require('fs');
const files = process.argv.slice(3);
let failed = false;
for (const f of files) {
  const src = fs.readFileSync(f, 'utf8');
  try {
    parser.parse(src, { sourceType: 'unambiguous', plugins: ['jsx'], errorRecovery: false });
    console.log('PARSE OK: ' + f);
  } catch (e) {
    failed = true;
    console.log('PARSE FAIL: ' + f + ' -> ' + e.message);
  }
}
process.exit(failed ? 1 : 0);
