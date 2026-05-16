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
  if (value === null || value === undefined) return null;
  if (typeof value === "number" || typeof value === "boolean") return value;
  return String(value);
}

function writeRecordsSheet(workbook, name, records, columns, options = {}) {
  const sheet = workbook.worksheets.add(name);
  const headers = columns.map((col) => col.header);
  const rows = records.map((record) => columns.map((col) => asScalar(record[col.key])));
  const matrix = [headers, ...rows];
  const lastCell = `${colLetter(headers.length - 1)}${matrix.length}`;
  sheet.getRange(`A1:${lastCell}`).values = matrix;
  sheet.getRange(`A1:${colLetter(headers.length - 1)}1`).format = {
    fill: { type: "solid", color: "#1F4E78" },
    font: { color: "#FFFFFF", bold: true, name: "Calibri", size: 11 },
    wrapText: true,
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: "#D9E2F3" },
  };
  if (matrix.length > 1) {
    sheet.getRange(`A2:${lastCell}`).format = {
      font: { name: "Calibri", size: 10, color: "#1F1F1F" },
      borders: { preset: "all", style: "thin", color: "#E5E7EB" },
      verticalAlignment: "center",
    };
  }
  for (const col of columns) {
    if (!col.numberFormat) continue;
    const colIdx = headers.indexOf(col.header);
    if (colIdx === -1 || matrix.length === 1) continue;
    sheet.getRange(`${colLetter(colIdx)}2:${colLetter(colIdx)}${matrix.length}`).format.numberFormat =
      col.numberFormat;
  }
  if (options.freezeHeader !== false) {
    sheet.freezePanes.freezeRows(1);
  }
  if (options.freezeColumns) {
    sheet.freezePanes.freezeColumns(options.freezeColumns);
  }
  return sheet;
}

async function saveBlob(blob, targetPath) {
  const bytes = Buffer.from(await blob.arrayBuffer());
  await fs.writeFile(targetPath, bytes);
}

const inputDir = process.argv[2];
const outputPath = process.argv[3];

if (!inputDir || !outputPath) {
  console.error("Usage: node build_formula_debug_report.mjs <inputDir> <outputXlsx>");
  process.exit(1);
}

const monthly = JSON.parse(await fs.readFile(path.join(inputDir, "monthly_returns.json"), "utf8"));
const selected = JSON.parse(await fs.readFile(path.join(inputDir, "selected_debug.json"), "utf8"));
const monthGrid = JSON.parse(await fs.readFile(path.join(inputDir, "monthly_grid.json"), "utf8"));
const meta = JSON.parse(await fs.readFile(path.join(inputDir, "run_meta.json"), "utf8"));

const workbook = Workbook.create();

const summarySheet = workbook.worksheets.add("Ozet");
summarySheet.getRange("A1:D12").values = [
  ["Backtest Formul Debug Raporu", null, null, null],
  ["Run ID", meta.run_id, "Komisyon Modeli", "Komisyonsuz"],
  ["Ilk Ay", meta.first_month, "Son Ay", meta.last_month],
  ["Ay Sayisi", meta.months, "Secilen Pozisyon", meta.selected_rows],
  ["Ortalama Aylik Getiri", meta.avg_monthly_return, "Toplam Getiri Carpani", meta.total_return_multiple],
  [null, null, null, null],
  ["X1 Formulu", "(TTM Net Kar / Ozsermaye) * (1 + Net Kar Buyumesi)", null, null],
  ["Net Kar Buyumesi", "(TTM Net Kar - Onceki TTM Net Kar) / Onceki TTM Net Kar", null, null],
  ["Buyume Kurali", "Ham buyume > 1.0 ise 100'e bolunur, sonra [-0.95, 3.0] araligina sikistirilir", null, null],
  ["X2 Formulu", "TTM Esas Faaliyet Kari / Firma Degeri", null, null],
  ["Firma Degeri", "Piyasa Degeri + Toplam Borc - Nakit", null, null],
  ["Piyasa Degeri", "Firma Degeri Fiyati * Pay Sayisi", null, null],
];
summarySheet.getRange("A1:D12").format = {
  font: { name: "Calibri", size: 11, color: "#1F1F1F" },
  verticalAlignment: "center",
  wrapText: true,
};
summarySheet.getRange("A1:D1").merge();
summarySheet.getRange("A1:D1").format = {
  fill: { type: "solid", color: "#1F4E78" },
  font: { color: "#FFFFFF", bold: true, size: 14, name: "Calibri" },
};
summarySheet.getRange("A2:A12").format = {
  fill: { type: "solid", color: "#D9EAF7" },
  font: { bold: true, name: "Calibri", size: 11, color: "#1F1F1F" },
};
summarySheet.getRange("C2:C5").format = {
  fill: { type: "solid", color: "#D9EAF7" },
  font: { bold: true, name: "Calibri", size: 11, color: "#1F1F1F" },
};
summarySheet.getRange("A:A").format.columnWidthPx = 180;
summarySheet.getRange("B:B").format.columnWidthPx = 420;
summarySheet.getRange("C:C").format.columnWidthPx = 170;
summarySheet.getRange("D:D").format.columnWidthPx = 180;
summarySheet.getRange("B5:D5").format.numberFormat = "0.00%";
summarySheet.freezePanes.freezeRows(1);

const gridSheet = writeRecordsSheet(
  workbook,
  "Aylik Liste",
  monthGrid,
  [
    { key: "month", header: "Ay" },
    { key: "rank_1", header: "Sira 1" },
    { key: "rank_2", header: "Sira 2" },
    { key: "rank_3", header: "Sira 3" },
    { key: "rank_4", header: "Sira 4" },
    { key: "rank_5", header: "Sira 5" },
  ],
  { freezeColumns: 1 },
);
gridSheet.getRange("A:A").format.columnWidthPx = 95;
gridSheet.getRange("B:F").format.columnWidthPx = 110;

const monthlySheet = writeRecordsSheet(
  workbook,
  "Aylik Getiriler",
  monthly,
  [
    { key: "month", header: "Ay" },
    { key: "buy_date", header: "Alis Tarihi" },
    { key: "sell_date", header: "Satis Tarihi" },
    { key: "gross_return", header: "Brut Getiri", numberFormat: "0.00%" },
    { key: "net_return", header: "Net Getiri", numberFormat: "0.00%" },
    { key: "portfolio_value_start", header: "Portfoy Baslangic", numberFormat: "#,##0.00" },
    { key: "portfolio_value_end", header: "Portfoy Bitis", numberFormat: "#,##0.00" },
    { key: "selected_symbols", header: "Secilen Hisseler" },
  ],
  { freezeColumns: 1 },
);
monthlySheet.getRange("A:H").format.columnWidthPx = 120;

const selectedSheet = writeRecordsSheet(
  workbook,
  "Secilen Pozisyonlar",
  selected,
  [
    { key: "month", header: "Ay" },
    { key: "rank_in_month", header: "Sira" },
    { key: "symbol", header: "Sembol" },
    { key: "score", header: "Skor", numberFormat: "0.000000" },
    { key: "x1", header: "X1", numberFormat: "0.000000" },
    { key: "x2", header: "X2", numberFormat: "0.000000" },
    { key: "buy_date", header: "Alis Tarihi" },
    { key: "buy_price", header: "Alis Fiyati", numberFormat: "#,##0.0000" },
    { key: "sell_date", header: "Satis Tarihi" },
    { key: "sell_price", header: "Satis Fiyati", numberFormat: "#,##0.0000" },
    { key: "gross_return", header: "Brut Getiri", numberFormat: "0.00%" },
    { key: "net_return", header: "Net Getiri", numberFormat: "0.00%" },
    { key: "used_period_end", header: "Kullanilan Donem Sonu" },
    { key: "used_announcement_datetime", header: "Kullanilan Aciklama Zamani" },
    { key: "source_statement_id", header: "Kaynak Tablo ID" },
  ],
  { freezeColumns: 3 },
);
selectedSheet.getRange("A:C").format.columnWidthPx = 90;
selectedSheet.getRange("D:F").format.columnWidthPx = 95;
selectedSheet.getRange("G:O").format.columnWidthPx = 120;

const formulaSheet = writeRecordsSheet(
  workbook,
  "Formul Verileri",
  selected,
  [
    { key: "month", header: "Ay" },
    { key: "rank_in_month", header: "Sira" },
    { key: "symbol", header: "Sembol" },
    { key: "net_income_ttm", header: "TTM Net Kar", numberFormat: "#,##0.00" },
    { key: "previous_net_income_ttm", header: "Onceki TTM Net Kar", numberFormat: "#,##0.00" },
    { key: "raw_growth", header: "Ham Buyume", numberFormat: "0.000000" },
    { key: "net_income_growth", header: "Normalize Buyume", numberFormat: "0.000000" },
    { key: "growth_multiplier", header: "Buyume Carpani", numberFormat: "0.000000" },
    { key: "equity", header: "Ozsermaye", numberFormat: "#,##0.00" },
    { key: "roe_component", header: "ROE Bileseni", numberFormat: "0.000000" },
    { key: "operating_profit_ttm", header: "TTM Esas Faaliyet Kari", numberFormat: "#,##0.00" },
    { key: "firm_value_price", header: "Firma Degeri Fiyati", numberFormat: "#,##0.0000" },
    { key: "shares_outstanding", header: "Pay Sayisi", numberFormat: "#,##0.00" },
    { key: "market_cap", header: "Piyasa Degeri", numberFormat: "#,##0.00" },
    { key: "total_debt", header: "Toplam Borc", numberFormat: "#,##0.00" },
    { key: "cash", header: "Cash", numberFormat: "#,##0.00" },
    { key: "firm_value", header: "Firma Degeri", numberFormat: "#,##0.00" },
    { key: "x1", header: "Kayitli X1", numberFormat: "0.000000" },
    { key: "x1_recalc", header: "Yeniden Hesap X1", numberFormat: "0.000000" },
    { key: "x1_diff", header: "X1 Farki", numberFormat: "0.000000" },
    { key: "x2", header: "Kayitli X2", numberFormat: "0.000000" },
    { key: "x2_recalc", header: "Yeniden Hesap X2", numberFormat: "0.000000" },
    { key: "x2_diff", header: "X2 Farki", numberFormat: "0.000000" },
    { key: "score", header: "Kayitli Skor", numberFormat: "0.000000" },
    { key: "score_recalc", header: "Yeniden Hesap Skor", numberFormat: "0.000000" },
    { key: "score_diff", header: "Skor Farki", numberFormat: "0.000000" },
    { key: "firm_value_price_date", header: "FD Fiyat Tarihi" },
    { key: "shares_announcement_datetime", header: "Pay Aciklama Zamani" },
    { key: "source_url", header: "Tablo Kaynak URL" },
    { key: "shares_source_url", header: "Pay Kaynak URL" },
  ],
  { freezeColumns: 3 },
);
formulaSheet.getRange("A:C").format.columnWidthPx = 90;
formulaSheet.getRange("D:Z").format.columnWidthPx = 115;
formulaSheet.getRange("AA:AD").format.columnWidthPx = 180;

const guideSheet = writeRecordsSheet(
  workbook,
  "Formul Rehberi",
  selected.slice(0, 5),
  [
    { key: "month", header: "Ay" },
    { key: "symbol", header: "Sembol" },
    { key: "x1_formula", header: "X1 Formulu" },
    { key: "x2_formula", header: "X2 Formulu" },
    { key: "score_formula", header: "Skor Formulu" },
  ],
  { freezeColumns: 2 },
);
guideSheet.getRange("A:B").format.columnWidthPx = 100;
guideSheet.getRange("C:E").format.columnWidthPx = 260;

const summaryInspect = await workbook.inspect({
  kind: "table",
  range: "Ozet!A1:D12",
  include: "values",
  tableMaxRows: 12,
  tableMaxCols: 4,
});
console.log("SUMMARY_INSPECT");
console.log(summaryInspect.ndjson);

const summaryPng = await workbook.render({ sheetName: "Ozet", range: "A1:D12", format: "png" });
const gridPng = await workbook.render({ sheetName: "Aylik Liste", range: "A1:F15", format: "png" });

const outputDir = path.dirname(outputPath);
await fs.mkdir(outputDir, { recursive: true });
await saveBlob(summaryPng, path.join(outputDir, "formula_debug_summary.png"));
await saveBlob(gridPng, path.join(outputDir, "formula_debug_month_grid.png"));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`XLSX_SAVED ${outputPath}`);
