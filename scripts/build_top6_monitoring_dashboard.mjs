import fs from "node:fs/promises";
import path from "node:path";

import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

function colLetter(index) {
  let n = index + 1;
  let out = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    out = String.fromCharCode(65 + rem) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

function asScalar(value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed !== "" && !Number.isNaN(Number(trimmed))) return Number(trimmed);
    return value;
  }
  return String(value);
}

function writeSheet(workbook, name, records, columns, options = {}) {
  const sheet = workbook.worksheets.add(name);
  const headers = columns.map((col) => col.header);
  const rows = records.map((record) => columns.map((col) => asScalar(record[col.key])));
  const matrix = [headers, ...rows];
  const lastCell = `${colLetter(headers.length - 1)}${matrix.length}`;
  sheet.getRange(`A1:${lastCell}`).values = matrix;
  sheet.getRange(`A1:${colLetter(headers.length - 1)}1`).format = {
    fill: { type: "solid", color: "#123B5D" },
    font: { color: "#FFFFFF", bold: true, name: "Calibri", size: 11 },
    wrapText: true,
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: "#D6E0EA" },
  };
  if (matrix.length > 1) {
    sheet.getRange(`A2:${lastCell}`).format = {
      font: { name: "Calibri", size: 10, color: "#1F1F1F" },
      borders: { preset: "all", style: "thin", color: "#E5E7EB" },
      verticalAlignment: "center",
    };
  }
  for (const col of columns) {
    const idx = headers.indexOf(col.header);
    if (idx === -1) continue;
    const letter = colLetter(idx);
    if (col.numberFormat && matrix.length > 1) {
      sheet.getRange(`${letter}2:${letter}${matrix.length}`).format.numberFormat = col.numberFormat;
    }
    sheet.getRange(`${letter}:${letter}`).format.columnWidthPx = col.widthPx ?? 110;
  }
  if (options.freezeHeader !== false) sheet.freezePanes.freezeRows(1);
  if (options.freezeColumns) sheet.freezePanes.freezeColumns(options.freezeColumns);
  return sheet;
}

const inputPath = process.argv[2];
const outputPath = process.argv[3];

if (!inputPath || !outputPath) {
  console.error("Usage: node build_top6_monitoring_dashboard.mjs <bundleJson> <outputXlsx>");
  process.exit(1);
}

const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
const workbook = Workbook.create();

const s = data.summary;
const dashboard = workbook.worksheets.add("Dashboard");
dashboard.getRange("A1:F20").values = [
  ["Accepted Guard Top6 Monitoring Dashboard", null, null, null, null, null],
  ["Run ID", "a285f6f1-c472-4b84-83e6-682fab9cfc47", "Coverage Dir", "backtest_coverage_a285f6f1", null, null],
  ["First Month", s.first_month, "Last Month", s.last_month, "Months", s.month_count],
  ["Positions", s.position_count, "Unique Symbols", s.unique_symbol_count, "Open-gap Ratio", s.open_gap_position_ratio],
  ["Initial Capital", s.initial_capital, "Ending Capital", s.ending_capital, "Multiple", s.ending_capital / s.initial_capital],
  ["Avg Monthly Return", s.avg_monthly_return, "Median Monthly Return", s.median_monthly_return, "Worst Month", s.worst_month_return],
  ["Best Month", s.best_month_return, "High Confidence Pos", s.high_confidence_positions, "Medium Confidence Pos", s.medium_confidence_positions],
  ["Core View", "Top6 accepted baseline is stable enough for monitoring; current task is not new filters but ongoing regime and symbol-health tracking.", null, null, null, null],
  [null, null, null, null, null, null],
  ["Top Contributors", "YAPRK", "DESA", "TUKAS", "SANFM", "CVKMD"],
  ["Weak Repeaters", "MERKO", "RTALB", "TUCLK", "DURDO", "YUNSA"],
  ["Worst Quarters", "2021Q2", "2026Q2", "2023Q1", "2025Q1", "2021Q3"],
  ["Notes", "Use Monthly Trend + Weak Quarter sheets to inspect regime breaks, and Symbol Health for recurring winners/losers.", null, null, null, null],
];
dashboard.getRange("A1:F20").format = {
  font: { name: "Calibri", size: 11, color: "#1F1F1F" },
  verticalAlignment: "center",
  wrapText: true,
};
dashboard.getRange("A1:F1").merge();
dashboard.getRange("A1:F1").format = {
  fill: { type: "solid", color: "#123B5D" },
  font: { color: "#FFFFFF", bold: true, size: 14, name: "Calibri" },
};
dashboard.getRange("A2:A13").format = {
  fill: { type: "solid", color: "#DBEAFE" },
  font: { bold: true, name: "Calibri", size: 11, color: "#1F1F1F" },
};
dashboard.getRange("C2:C7").format = {
  fill: { type: "solid", color: "#DBEAFE" },
  font: { bold: true, name: "Calibri", size: 11, color: "#1F1F1F" },
};
dashboard.getRange("E3:E7").format = {
  fill: { type: "solid", color: "#DBEAFE" },
  font: { bold: true, name: "Calibri", size: 11, color: "#1F1F1F" },
};
dashboard.getRange("B4:F7").format.numberFormat = "0.00%";
dashboard.getRange("B5:D5").format.numberFormat = "#,##0.00";
dashboard.getRange("A:A").format.columnWidthPx = 165;
dashboard.getRange("B:B").format.columnWidthPx = 180;
dashboard.getRange("C:C").format.columnWidthPx = 165;
dashboard.getRange("D:D").format.columnWidthPx = 180;
dashboard.getRange("E:E").format.columnWidthPx = 160;
dashboard.getRange("F:F").format.columnWidthPx = 130;
dashboard.freezePanes.freezeRows(1);

writeSheet(
  workbook,
  "Monthly Trend",
  data.equity_curve,
  [
    { key: "month", header: "Month", widthPx: 90 },
    { key: "portfolio_value_end", header: "Portfolio End", numberFormat: "#,##0.00", widthPx: 120 },
    { key: "net_return", header: "Net Return", numberFormat: "0.00%", widthPx: 100 },
    { key: "drawdown", header: "Drawdown", numberFormat: "0.00%", widthPx: 100 },
  ],
  { freezeColumns: 1 },
);

writeSheet(
  workbook,
  "Quarterly Trend",
  data.quarterly_returns,
  [
    { key: "quarter", header: "Quarter", widthPx: 90 },
    { key: "months", header: "Months", widthPx: 180 },
    { key: "quarter_return", header: "Quarter Return", numberFormat: "0.00%", widthPx: 110 },
    { key: "portfolio_value_start", header: "Start", numberFormat: "#,##0.00", widthPx: 110 },
    { key: "portfolio_value_end", header: "End", numberFormat: "#,##0.00", widthPx: 110 },
  ],
  { freezeColumns: 1 },
);

writeSheet(
  workbook,
  "Best Symbols",
  data.best_symbols,
  [
    { key: "symbol", header: "Symbol", widthPx: 90 },
    { key: "selected_months", header: "Months", numberFormat: "0", widthPx: 70 },
    { key: "net_contribution", header: "Net Contribution", numberFormat: "0.00%", widthPx: 110 },
    { key: "positive_share", header: "Positive Share", numberFormat: "0%", widthPx: 100 },
    { key: "avg_score", header: "Avg Score", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x1", header: "Avg X1", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x2", header: "Avg X2", numberFormat: "0.000", widthPx: 90 },
  ],
  { freezeColumns: 1 },
);

writeSheet(
  workbook,
  "Worst Symbols",
  data.worst_symbols,
  [
    { key: "symbol", header: "Symbol", widthPx: 90 },
    { key: "selected_months", header: "Months", numberFormat: "0", widthPx: 70 },
    { key: "net_contribution", header: "Net Contribution", numberFormat: "0.00%", widthPx: 110 },
    { key: "positive_share", header: "Positive Share", numberFormat: "0%", widthPx: 100 },
    { key: "avg_score", header: "Avg Score", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x1", header: "Avg X1", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x2", header: "Avg X2", numberFormat: "0.000", widthPx: 90 },
  ],
  { freezeColumns: 1 },
);

writeSheet(
  workbook,
  "Repeated Names",
  data.most_repeated_symbols,
  [
    { key: "symbol", header: "Symbol", widthPx: 90 },
    { key: "selected_months", header: "Months", numberFormat: "0", widthPx: 70 },
    { key: "selection_rate", header: "Selection Rate", numberFormat: "0.0%", widthPx: 100 },
    { key: "net_contribution", header: "Net Contribution", numberFormat: "0.00%", widthPx: 110 },
    { key: "avg_score", header: "Avg Score", numberFormat: "0.000", widthPx: 90 },
  ],
  { freezeColumns: 1 },
);

writeSheet(
  workbook,
  "Weak Quarters",
  data.weak_quarter_contributors,
  [
    { key: "quarter", header: "Quarter", widthPx: 90 },
    { key: "symbol", header: "Symbol", widthPx: 90 },
    { key: "selected_months_in_quarter", header: "Months", numberFormat: "0", widthPx: 70 },
    { key: "net_contribution", header: "Net Contribution", numberFormat: "0.00%", widthPx: 110 },
    { key: "avg_score", header: "Avg Score", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x1", header: "Avg X1", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x2", header: "Avg X2", numberFormat: "0.000", widthPx: 90 },
  ],
  { freezeColumns: 2 },
);

writeSheet(
  workbook,
  "Weak Month Compare",
  data.weak_same_month_compare,
  [
    { key: "month", header: "Month", widthPx: 90 },
    { key: "weak_count", header: "Weak Count", numberFormat: "0", widthPx: 80 },
    { key: "other_count", header: "Other Count", numberFormat: "0", widthPx: 80 },
    { key: "weak_avg_return", header: "Weak Avg Return", numberFormat: "0.00%", widthPx: 110 },
    { key: "other_avg_return", header: "Other Avg Return", numberFormat: "0.00%", widthPx: 110 },
    { key: "weak_avg_score", header: "Weak Avg Score", numberFormat: "0.000", widthPx: 90 },
    { key: "other_avg_score", header: "Other Avg Score", numberFormat: "0.000", widthPx: 90 },
  ],
  { freezeColumns: 1 },
);

writeSheet(
  workbook,
  "Concentration",
  data.concentration_months,
  [
    { key: "rebalance_month", header: "Month", widthPx: 90 },
    { key: "position_count", header: "Positions", numberFormat: "0", widthPx: 80 },
    { key: "top_abs_contribution_share", header: "Top Abs Share", numberFormat: "0.00%", widthPx: 110 },
    { key: "top_contributor_symbol", header: "Top Symbol", widthPx: 90 },
    { key: "month_return", header: "Month Return", numberFormat: "0.00%", widthPx: 100 },
    { key: "avg_score", header: "Avg Score", numberFormat: "0.000", widthPx: 90 },
    { key: "x1_dominant_share", header: "X1 Dominant Share", numberFormat: "0.0%", widthPx: 110 },
  ],
  { freezeColumns: 1 },
);

await workbook.inspect({
  kind: "table",
  range: "Dashboard!A1:F13",
  include: "values",
  tableMaxRows: 20,
  tableMaxCols: 6,
});
await workbook.render({ sheetName: "Dashboard", range: "A1:F13", format: "png" });
await workbook.render({ sheetName: "Quarterly Trend", range: "A1:E15", format: "png" });

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`XLSX_SAVED ${outputPath}`);
