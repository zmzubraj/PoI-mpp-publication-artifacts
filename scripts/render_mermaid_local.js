#!/usr/bin/env node

"use strict";

const fs = require("node:fs");
const path = require("node:path");

function usage() {
  throw new Error(
    "usage: render_mermaid_local.js <input.mmd> <output.svg|output.png> " +
      "(requires PLAYWRIGHT_MODULE and MERMAID_BUNDLE)"
  );
}

async function main() {
  const [, , inputArg, outputArg] = process.argv;
  if (!inputArg || !outputArg) usage();

  const inputPath = path.resolve(inputArg);
  const outputPath = path.resolve(outputArg);
  const extension = path.extname(outputPath).toLowerCase();
  if (!new Set([".svg", ".png"]).has(extension)) usage();

  const playwrightModule = process.env.PLAYWRIGHT_MODULE;
  const mermaidBundle = process.env.MERMAID_BUNDLE;
  if (!playwrightModule || !mermaidBundle) usage();

  const { chromium } = require(playwrightModule);
  const source = fs.readFileSync(inputPath, "utf8");
  const executablePath = process.env.CHROME_EXECUTABLE;
  const browser = await chromium.launch({
    headless: true,
    ...(executablePath ? { executablePath: path.resolve(executablePath) } : {}),
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1800, height: 1200 },
      deviceScaleFactor: 2,
    });
    await page.setContent(
      "<!doctype html><html><head><meta charset=\"utf-8\">" +
        "<style>html,body{margin:0;background:#fff}#diagram{display:inline-block;padding:24px}</style>" +
        "</head><body><div id=\"diagram\"></div></body></html>"
    );
    await page.addScriptTag({ path: path.resolve(mermaidBundle) });
    const svg = await page.evaluate(async (diagramSource) => {
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: "base",
        flowchart: { htmlLabels: false, curve: "basis" },
        sequence: { useMaxWidth: true, wrap: true },
        themeVariables: {
          fontFamily: "Arial, Helvetica, sans-serif",
          primaryColor: "#eef4fb",
          primaryTextColor: "#102a43",
          primaryBorderColor: "#486581",
          lineColor: "#334e68",
          secondaryColor: "#f6f8fa",
          tertiaryColor: "#fff7e6",
        },
      });
      const rendered = await mermaid.render("poi-publication-diagram", diagramSource);
      document.getElementById("diagram").innerHTML = rendered.svg;
      return rendered.svg;
    }, source);

    fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    if (extension === ".svg") {
      fs.writeFileSync(outputPath, svg, "utf8");
    } else {
      const element = page.locator("#diagram");
      await element.screenshot({ path: outputPath, omitBackground: false });
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
