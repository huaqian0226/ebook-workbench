// Compile the two fork modules against the pinned upstream runtime's CommonJS/legacy Nest decorators.
const fs = require("node:fs");
const ts = require("./typescript.cjs");
fs.mkdirSync("out");
for (const file of ["direct-download.service", "chapter-file"]) {
  const source = fs.readFileSync(file + ".ts", "utf8");
  const result = ts.transpileModule(source, {
    fileName: file + ".ts",
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2023,
      experimentalDecorators: true,
      emitDecoratorMetadata: true,
      esModuleInterop: true,
    },
  });
  fs.writeFileSync("out/" + file + ".js", result.outputText);
}
