#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const {
  AlignmentType,
  BorderStyle,
  Document,
  ExternalHyperlink,
  Footer,
  Header,
  HeadingLevel,
  PageBreak,
  PageNumber,
  Packer,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableLayoutType,
  TableRow,
  TextRun,
  WidthType,
} = require("docx");

const REPO_ROOT = path.resolve(__dirname, "..");
const DEFAULT_SOURCE = path.join(
  REPO_ROOT,
  "docs/paper_artifacts/final/manuscript/POI_SUBMISSION_MANUSCRIPT.md",
);
const DEFAULT_OUTPUT = path.join(
  REPO_ROOT,
  "docs/paper_artifacts/final/deliverables/POI_MPP_PUBLICATION_DRAFT.docx",
);
const MANIFEST_PATH = path.join(REPO_ROOT, "publication/artifact_manifest.json");
const MANIFEST_SHA256 = "bd882ca072602e13cc14850a44d1b769111f6b032e56901e9419a3263593c";

const sourcePath = path.resolve(process.argv[2] || DEFAULT_SOURCE);
const outputPath = path.resolve(process.argv[3] || DEFAULT_OUTPUT);

function inlineRuns(text, base = {}) {
  const pattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)]+\))/g;
  const parts = text.split(pattern).filter(Boolean);
  return parts.map((part) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return new TextRun({ ...base, text: part.slice(2, -2), bold: true });
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return new TextRun({ ...base, text: part.slice(1, -1), italics: true });
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return new TextRun({
        ...base,
        text: part.slice(1, -1),
        font: "Courier New",
        color: "1F4E5F",
        shading: { type: ShadingType.CLEAR, fill: "E9F2F4" },
      });
    }
    const match = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/);
    if (match) {
      return new ExternalHyperlink({
        link: match[2],
        children: [new TextRun({ ...base, text: match[1], color: "0563C1", underline: {} })],
      });
    }
    return new TextRun({ ...base, text: part });
  });
}

function markdownTable(lines) {
  const parsed = lines
    .filter((line) => !/^\s*\|?\s*:?-{3,}/.test(line))
    .map((line) => line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim()));
  if (parsed.length === 0) return null;
  const columns = Math.max(...parsed.map((row) => row.length));
  const columnWidth = Math.floor(100 / columns);
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    layout: TableLayoutType.AUTOFIT,
    rows: parsed.map(
      (row, rowIndex) =>
        new TableRow({
          tableHeader: rowIndex === 0,
          cantSplit: true,
          children: Array.from({ length: columns }, (_, columnIndex) =>
            new TableCell({
              width: { size: columnWidth, type: WidthType.PERCENTAGE },
              shading:
                rowIndex === 0
                  ? { type: ShadingType.CLEAR, fill: "D9EAF0" }
                  : rowIndex % 2 === 0
                    ? { type: ShadingType.CLEAR, fill: "F4F7F8" }
                    : undefined,
              margins: { top: 80, bottom: 80, left: 90, right: 90 },
              children: [
                new Paragraph({
                  spacing: { after: 0 },
                  children: inlineRuns(row[columnIndex] || "", {
                    size: 18,
                    bold: rowIndex === 0,
                  }),
                }),
              ],
            }),
          ),
        }),
    ),
  });
}

function collapseWrappedLines(markdown) {
  const rawLines = markdown.replace(/\r\n/g, "\n").split("\n");
  const lines = [];
  let prose = [];
  let inCode = false;

  const flushProse = () => {
    if (prose.length > 0) {
      lines.push(prose.join(" "));
      prose = [];
    }
  };
  const isStructural = (line) =>
    line.trim() === "" ||
    /^(#{1,4})\s+/.test(line) ||
    /^\s*[-*]\s+/.test(line) ||
    /^\s*\d+\.\s+/.test(line) ||
    /^>\s+/.test(line) ||
    /^---+$/.test(line.trim()) ||
    /^\s*\|/.test(line);

  for (const line of rawLines) {
    if (line.startsWith("```")) {
      flushProse();
      lines.push(line);
      inCode = !inCode;
    } else if (inCode) {
      lines.push(line);
    } else if (isStructural(line)) {
      flushProse();
      lines.push(line);
    } else {
      prose.push(line.trim());
    }
  }
  flushProse();
  return lines;
}

function markdownToDocx(markdown) {
  const lines = collapseWrappedLines(markdown);
  const children = [];
  let inCode = false;
  let code = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.startsWith("```")) {
      if (inCode) {
        children.push(
          new Paragraph({
            keepLines: true,
            spacing: { before: 100, after: 160 },
            shading: { type: ShadingType.CLEAR, fill: "F2F2F2" },
            border: {
              left: { style: BorderStyle.SINGLE, size: 8, color: "1F4E5F", space: 6 },
            },
            children: [new TextRun({ text: code.join("\n"), font: "Courier New", size: 18 })],
          }),
        );
        code = [];
      }
      inCode = !inCode;
      continue;
    }
    if (inCode) {
      code.push(line);
      continue;
    }
    if (/^\s*\|/.test(line) && lines[index + 1] && /\|\s*:?-{3,}/.test(lines[index + 1])) {
      const tableLines = [line];
      while (index + 1 < lines.length && /^\s*\|/.test(lines[index + 1])) {
        tableLines.push(lines[index + 1]);
        index += 1;
      }
      const table = markdownTable(tableLines);
      if (table) children.push(table, new Paragraph({ spacing: { after: 80 } }));
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const levels = [
        HeadingLevel.TITLE,
        HeadingLevel.HEADING_1,
        HeadingLevel.HEADING_2,
        HeadingLevel.HEADING_3,
      ];
      children.push(
        new Paragraph({
          heading: levels[heading[1].length - 1],
          keepNext: true,
          children: inlineRuns(heading[2]),
        }),
      );
      continue;
    }
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) {
      children.push(
        new Paragraph({
          bullet: { level: 0 },
          spacing: { after: 60 },
          children: inlineRuns(bullet[1]),
        }),
      );
      continue;
    }
    const numbered = line.match(/^\s*(\d+)\.\s+(.+)$/);
    if (numbered) {
      children.push(
        new Paragraph({
          indent: { left: 420, hanging: 220 },
          spacing: { after: 60 },
          children: [new TextRun({ text: `${numbered[1]}.\t`, bold: true }), ...inlineRuns(numbered[2])],
        }),
      );
      continue;
    }
    if (/^---+$/.test(line.trim())) {
      children.push(
        new Paragraph({
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "A7B7BE" } },
          spacing: { before: 80, after: 120 },
        }),
      );
      continue;
    }
    if (line.startsWith("> ")) {
      children.push(
        new Paragraph({
          indent: { left: 360 },
          border: { left: { style: BorderStyle.SINGLE, size: 8, color: "4F8FA3", space: 8 } },
          children: inlineRuns(line.slice(2), { italics: true, color: "3E4D53" }),
        }),
      );
      continue;
    }
    if (line.trim() === "") {
      continue;
    }
    children.push(
      new Paragraph({
        spacing: { after: 120, line: 280 },
        widowControl: true,
        children: inlineRuns(line),
      }),
    );
  }
  return children;
}

async function main() {
  const markdown = fs.readFileSync(sourcePath, "utf8");
  const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, "utf8"));
  if (!Array.isArray(manifest.outputs) || manifest.outputs.length !== 36) {
    throw new Error("canonical manifest must contain exactly 36 outputs");
  }
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });

  const cover = [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 1800, after: 240 },
      children: [new TextRun({ text: "Proof of Intelligence Consensus Architecture", font: "Arial", bold: true, size: 42, color: "173B4A" })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 600 },
      children: [new TextRun({ text: "Evidence-bound Minimum Publishable Prototype draft", font: "Arial", size: 26, color: "4F7180" })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      shading: { type: ShadingType.CLEAR, fill: "FFF2CC" },
      border: {
        top: { style: BorderStyle.SINGLE, size: 6, color: "D6B656" },
        bottom: { style: BorderStyle.SINGLE, size: 6, color: "D6B656" },
        left: { style: BorderStyle.SINGLE, size: 6, color: "D6B656" },
        right: { style: BorderStyle.SINGLE, size: 6, color: "D6B656" },
      },
      spacing: { before: 240, after: 240 },
      children: [
        new TextRun({
          text: "NOT PUBLICATION-READY: E3 external evaluator authority, authenticated independent manual review, and the freeze sentinel remain open.",
          bold: true,
          size: 22,
          color: "7F6000",
        }),
      ],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 600, after: 120 },
      children: [new TextRun({ text: "Canonical report manifest SHA-256", bold: true, size: 20 })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: MANIFEST_SHA256, font: "Courier New", size: 17, color: "1F4E5F" })],
    }),
    new Paragraph({ children: [new PageBreak()] }),
  ];

  const document = new Document({
    creator: "PoI MPP publication artifact pipeline",
    title: "Proof of Intelligence Consensus Architecture — Evidence-bound MPP draft",
    subject: "Canonical manuscript export; not publication-ready",
    description: `Generated from ${path.relative(REPO_ROOT, sourcePath)} and canonical manifest ${MANIFEST_SHA256}`,
    styles: {
      default: {
        document: { run: { font: "Arial", size: 21, color: "202A2E" } },
        title: { run: { font: "Arial", size: 34, bold: true, color: "173B4A" }, paragraph: { spacing: { after: 260 } } },
        heading1: { run: { font: "Arial", size: 30, bold: true, color: "173B4A" }, paragraph: { spacing: { before: 300, after: 140 } } },
        heading2: { run: { font: "Arial", size: 25, bold: true, color: "24586B" }, paragraph: { spacing: { before: 240, after: 100 } } },
        heading3: { run: { font: "Arial", size: 22, bold: true, color: "3E7081" }, paragraph: { spacing: { before: 180, after: 80 } } },
      },
    },
    numbering: {
      config: [
        {
          reference: "publication-numbering",
          levels: [{ level: 0, format: "decimal", text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 420, hanging: 220 } } } }],
        },
      ],
    },
    sections: [
      {
        properties: {
          page: {
            margin: { top: 900, right: 900, bottom: 900, left: 900, header: 360, footer: 360 },
          },
        },
        headers: {
          default: new Header({
            children: [
              new Paragraph({
                alignment: AlignmentType.RIGHT,
                border: { bottom: { style: BorderStyle.SINGLE, size: 2, color: "A7B7BE" } },
                children: [new TextRun({ text: "PoI MPP | Evidence-bound draft", size: 17, color: "607D89" })],
              }),
            ],
          }),
        },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [
                  new TextRun({ text: "Not publication-ready  •  Page ", size: 17, color: "607D89" }),
                  new TextRun({ children: [PageNumber.CURRENT], size: 17, color: "607D89" }),
                ],
              }),
            ],
          }),
        },
        children: [...cover, ...markdownToDocx(markdown)],
      },
    ],
  });

  const buffer = await Packer.toBuffer(document);
  fs.writeFileSync(outputPath, buffer);
  process.stdout.write(`${outputPath}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
