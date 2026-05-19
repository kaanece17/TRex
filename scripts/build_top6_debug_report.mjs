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

function titleCase(text) {
  return String(text).replaceAll("_", " ");
}

function writeRecordsSheet(workbook, name, records, columns, options = {}) {
  const sheet = workbook.worksheets.add(name);
  const headers = columns.map((col) => col.header);
  const rows = records.map((record) => columns.map((col) => asScalar(record[col.key])));
  const matrix = [headers, ...rows];
  const lastCell = `${colLetter(headers.length - 1)}${matrix.length}`;
  sheet.getRange(`A1:${lastCell}`).values = matrix;
  sheet.getRange(`A1:${colLetter(headers.length - 1)}1`).format = {
    fill: { type: "solid", color: "#163B65" },
    font: { color: "#FFFFFF", bold: true, name: "Calibri", size: 11 },
    wrapText: true,
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: "#D4DCE6" },
  };
  if (matrix.length > 1) {
    sheet.getRange(`A2:${lastCell}`).format = {
      font: { name: "Calibri", size: 10, color: "#1F1F1F" },
      borders: { preset: "all", style: "thin", color: "#E5E7EB" },
      verticalAlignment: "center",
    };
  }
  for (const col of columns) {
    const colIdx = headers.indexOf(col.header);
    if (colIdx === -1) continue;
    const letter = colLetter(colIdx);
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
  console.error("Usage: node build_top6_debug_report.mjs <bundleJson> <outputXlsx>");
  process.exit(1);
}

const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
const workbook = Workbook.create();

const summary = data.coverage_summary;
const summarySheet = workbook.worksheets.add("Ozet");
summarySheet.getRange("A1:D18").values = [
  ["Accepted Guard Top6 Debug Raporu", null, null, null],
  ["Run ID", "a285f6f1-c472-4b84-83e6-682fab9cfc47", "Config", "config.formula_research.yaml"],
  ["Ilk Ay", summary.first_month, "Son Ay", summary.last_month],
  ["Ay Sayisi", summary.month_count, "Pozisyon Sayisi", summary.position_count],
  ["Benzersiz Sembol", summary.unique_symbol_count, "Open-gap Pozisyon", summary.positions_with_open_gap],
  ["Open-gap Orani", summary.open_gap_position_ratio, "Baslangic Sermayesi", summary.initial_capital],
  ["Bitis Sermayesi", summary.ending_capital, "Toplam Carpani", summary.ending_capital / summary.initial_capital],
  ["Ort. Aylik Getiri", summary.avg_monthly_return, "Median Aylik Getiri", summary.median_monthly_return],
  ["En Iyi Ay", summary.best_month_return, "En Kotu Ay", summary.worst_month_return],
  ["Ana Not", "Top6 accepted baseline, guard mantigi korunarak tek isim riski dagitildi.", null, null],
  ["Q En Kotu", "2021Q2 -27.40%", "Q En Iyi", "2022Q4 +102.77%"],
  ["Top Tasiyici", "YAPRK / DESA / TUKAS / SANFM / CVKMD", "Kronik Zayif", "MERKO / RTALB / TUCLK / DURDO / YUNSA"],
  ["Repeaters Teshis", "Zayif tekrar edenler ayni aylarda daha yuksek skorla ama daha kotu performansla geliyor.", null, null],
  ["FV/Eq Teshis", "En ucuz grup topluca kotu degil; 0.5-1.0 bandi daha zayif.", null, null],
  ["X1 Teshis", "Zayif x1 cepleri value-trap benzeri; ama dar filtre denemesi iyi calismadi.", null, null],
  ["Momentum Not", "Hard momentum candidate cok guclu ama kalite daha kirli oldugu icin baseline yapilmadi.", null, null],
  ["Debug Kullanim", "Bu workbook accepted top6 stratejisini ayri ayri delebilmek icin ozet + ham diagnostik sheetleri verir.", null, null],
  ["Durum", "Accepted baseline korunuyor.", null, null],
];
summarySheet.getRange("A1:D18").format = {
  font: { name: "Calibri", size: 11, color: "#1F1F1F" },
  verticalAlignment: "center",
  wrapText: true,
};
summarySheet.getRange("A1:D1").merge();
summarySheet.getRange("A1:D1").format = {
  fill: { type: "solid", color: "#163B65" },
  font: { color: "#FFFFFF", bold: true, size: 14, name: "Calibri" },
};
summarySheet.getRange("A2:A18").format = {
  fill: { type: "solid", color: "#DBEAFE" },
  font: { bold: true, name: "Calibri", size: 11, color: "#1F1F1F" },
};
summarySheet.getRange("C2:C12").format = {
  fill: { type: "solid", color: "#DBEAFE" },
  font: { bold: true, name: "Calibri", size: 11, color: "#1F1F1F" },
};
summarySheet.getRange("B6:D9").format.numberFormat = "0.00%";
summarySheet.getRange("B6:C7").format.numberFormat = "#,##0.00";
summarySheet.getRange("A:A").format.columnWidthPx = 170;
summarySheet.getRange("B:B").format.columnWidthPx = 320;
summarySheet.getRange("C:C").format.columnWidthPx = 170;
summarySheet.getRange("D:D").format.columnWidthPx = 220;
summarySheet.freezePanes.freezeRows(1);

writeRecordsSheet(
  workbook,
  "Ceyrek Getiriler",
  data.quarterly_returns,
  [
    { key: "quarter", header: "Ceyrek", widthPx: 100 },
    { key: "month_count", header: "Ay Adedi", numberFormat: "0", widthPx: 90 },
    { key: "months", header: "Aylar", widthPx: 180 },
    { key: "quarter_return", header: "Ceyrek Getirisi", numberFormat: "0.00%", widthPx: 120 },
    { key: "portfolio_value_start", header: "Baslangic", numberFormat: "#,##0.00", widthPx: 120 },
    { key: "portfolio_value_end", header: "Bitis", numberFormat: "#,##0.00", widthPx: 120 },
  ],
  { freezeColumns: 1 },
);

writeRecordsSheet(
  workbook,
  "En Zayif Ceyrekler",
  data.worst_quarters,
  [
    { key: "quarter", header: "Ceyrek", widthPx: 100 },
    { key: "months", header: "Aylar", widthPx: 180 },
    { key: "quarter_return", header: "Getiri", numberFormat: "0.00%", widthPx: 120 },
    { key: "portfolio_value_start", header: "Baslangic", numberFormat: "#,##0.00", widthPx: 120 },
    { key: "portfolio_value_end", header: "Bitis", numberFormat: "#,##0.00", widthPx: 120 },
  ],
  { freezeColumns: 1 },
);

writeRecordsSheet(
  workbook,
  "En Iyi Ceyrekler",
  data.best_quarters,
  [
    { key: "quarter", header: "Ceyrek", widthPx: 100 },
    { key: "months", header: "Aylar", widthPx: 180 },
    { key: "quarter_return", header: "Getiri", numberFormat: "0.00%", widthPx: 120 },
    { key: "portfolio_value_start", header: "Baslangic", numberFormat: "#,##0.00", widthPx: 120 },
    { key: "portfolio_value_end", header: "Bitis", numberFormat: "#,##0.00", widthPx: 120 },
  ],
  { freezeColumns: 1 },
);

writeRecordsSheet(
  workbook,
  "Zayif Ceyrek Katki",
  data.weak_quarter_symbol_contributors,
  [
    { key: "quarter", header: "Ceyrek", widthPx: 90 },
    { key: "symbol", header: "Sembol", widthPx: 90 },
    { key: "selected_months_in_quarter", header: "Ay", numberFormat: "0", widthPx: 70 },
    { key: "net_contribution", header: "Net Katki", numberFormat: "0.00%", widthPx: 100 },
    { key: "avg_score", header: "Ort Skor", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x1", header: "Ort X1", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x2", header: "Ort X2", numberFormat: "0.000", widthPx: 90 },
  ],
  { freezeColumns: 2 },
);

writeRecordsSheet(
  workbook,
  "En Iyi Semboller",
  data.best_symbols,
  [
    { key: "symbol", header: "Sembol", widthPx: 90 },
    { key: "selected_months", header: "Secim Ay", numberFormat: "0", widthPx: 80 },
    { key: "net_contribution", header: "Net Katki", numberFormat: "0.00%", widthPx: 100 },
    { key: "positive_share", header: "Pozitif Pay", numberFormat: "0%", widthPx: 90 },
    { key: "avg_score", header: "Ort Skor", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x1", header: "Ort X1", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x2", header: "Ort X2", numberFormat: "0.000", widthPx: 90 },
  ],
  { freezeColumns: 1 },
);

writeRecordsSheet(
  workbook,
  "En Kotu Semboller",
  data.worst_symbols,
  [
    { key: "symbol", header: "Sembol", widthPx: 90 },
    { key: "selected_months", header: "Secim Ay", numberFormat: "0", widthPx: 80 },
    { key: "net_contribution", header: "Net Katki", numberFormat: "0.00%", widthPx: 100 },
    { key: "positive_share", header: "Pozitif Pay", numberFormat: "0%", widthPx: 90 },
    { key: "avg_score", header: "Ort Skor", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x1", header: "Ort X1", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x2", header: "Ort X2", numberFormat: "0.000", widthPx: 90 },
  ],
  { freezeColumns: 1 },
);

writeRecordsSheet(
  workbook,
  "Tekrarlayanlar",
  data.most_repeated_symbols,
  [
    { key: "symbol", header: "Sembol", widthPx: 90 },
    { key: "selected_months", header: "Secim Ay", numberFormat: "0", widthPx: 80 },
    { key: "selection_rate", header: "Secim Orani", numberFormat: "0.0%", widthPx: 90 },
    { key: "net_contribution", header: "Net Katki", numberFormat: "0.00%", widthPx: 100 },
    { key: "avg_score", header: "Ort Skor", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x1", header: "Ort X1", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x2", header: "Ort X2", numberFormat: "0.000", widthPx: 90 },
  ],
  { freezeColumns: 1 },
);

writeRecordsSheet(
  workbook,
  "Weak vs Strong",
  data.repeaters_symbol_compare,
  [
    { key: "symbol", header: "Sembol", widthPx: 90 },
    { key: "selected_months", header: "Secim Ay", numberFormat: "0", widthPx: 80 },
    { key: "avg_return", header: "Ort Getiri", numberFormat: "0.00%", widthPx: 100 },
    { key: "avg_score", header: "Ort Skor", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x1_share", header: "Ort X1 Pay", numberFormat: "0.0%", widthPx: 90 },
    { key: "avg_growth", header: "Ort Buyume", numberFormat: "0.000", widthPx: 100 },
    { key: "avg_fv_to_equity", header: "Ort FV/Eq", numberFormat: "0.000", widthPx: 90 },
  ],
  { freezeColumns: 1 },
);

writeRecordsSheet(
  workbook,
  "Ayni Ay Kiyas",
  data.weak_repeaters_same_month_compare,
  [
    { key: "month", header: "Ay", widthPx: 90 },
    { key: "weak_count", header: "Weak Adet", numberFormat: "0", widthPx: 80 },
    { key: "other_count", header: "Diger Adet", numberFormat: "0", widthPx: 80 },
    { key: "weak_avg_return", header: "Weak Ort Getiri", numberFormat: "0.00%", widthPx: 110 },
    { key: "other_avg_return", header: "Diger Ort Getiri", numberFormat: "0.00%", widthPx: 110 },
    { key: "weak_avg_score", header: "Weak Ort Skor", numberFormat: "0.000", widthPx: 95 },
    { key: "other_avg_score", header: "Diger Ort Skor", numberFormat: "0.000", widthPx: 95 },
    { key: "weak_avg_fv_to_equity", header: "Weak FV/Eq", numberFormat: "0.000", widthPx: 90 },
    { key: "other_avg_fv_to_equity", header: "Diger FV/Eq", numberFormat: "0.000", widthPx: 90 },
  ],
  { freezeColumns: 1 },
);

writeRecordsSheet(
  workbook,
  "FV Eq Teshis",
  data.fv_equity_buckets,
  [
    { key: "fv_bucket", header: "FV/Eq Bant", widthPx: 100 },
    { key: "n", header: "Adet", numberFormat: "0", widthPx: 70 },
    { key: "avg_return", header: "Ort Getiri", numberFormat: "0.00%", widthPx: 100 },
    { key: "med_return", header: "Median Getiri", numberFormat: "0.00%", widthPx: 100 },
    { key: "avg_score", header: "Ort Skor", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x1_share", header: "Ort X1 Pay", numberFormat: "0.0%", widthPx: 95 },
    { key: "avg_growth", header: "Ort Buyume", numberFormat: "0.000", widthPx: 95 },
  ],
  { freezeColumns: 1 },
);

writeRecordsSheet(
  workbook,
  "X1 Ikinci Sinyal",
  data.x1_second_signal,
  [
    { key: "group", header: "Grup", widthPx: 180 },
    { key: "n", header: "Adet", numberFormat: "0", widthPx: 70 },
    { key: "avg_ret", header: "Ort Getiri", numberFormat: "0.00%", widthPx: 100 },
    { key: "med_ret", header: "Median Getiri", numberFormat: "0.00%", widthPx: 100 },
    { key: "avg_score", header: "Ort Skor", numberFormat: "0.000", widthPx: 90 },
    { key: "avg_x1_share", header: "Ort X1 Pay", numberFormat: "0.0%", widthPx: 95 },
    { key: "avg_growth", header: "Ort Buyume", numberFormat: "0.000", widthPx: 95 },
    { key: "avg_fv_to_equity", header: "Ort FV/Eq", numberFormat: "0.000", widthPx: 90 },
  ],
  { freezeColumns: 1 },
);

await workbook.inspect({
  kind: "table",
  range: "Ozet!A1:D18",
  include: "values",
  tableMaxRows: 20,
  tableMaxCols: 4,
});

await workbook.render({ sheetName: "Ozet", range: "A1:D18", format: "png" });
await workbook.render({ sheetName: "Ceyrek Getiriler", range: "A1:F16", format: "png" });

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`XLSX_SAVED ${outputPath}`);
