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

const inputDir = process.argv[2];
const outputPath = process.argv[3];

if (!inputDir || !outputPath) {
  console.error("Usage: node build_backtest_coverage_report.mjs <inputDir> <outputXlsx>");
  process.exit(1);
}

const summary = JSON.parse(await fs.readFile(path.join(inputDir, "summary.json"), "utf8"));
const monthly = JSON.parse(await fs.readFile(path.join(inputDir, "monthly_returns.json"), "utf8"));
const selected = JSON.parse(await fs.readFile(path.join(inputDir, "selected_positions.json"), "utf8"));
const selectedCoverage = JSON.parse(await fs.readFile(path.join(inputDir, "selected_coverage.json"), "utf8"));
const monthlyCoverage = JSON.parse(await fs.readFile(path.join(inputDir, "monthly_coverage.json"), "utf8"));
const openGaps = JSON.parse(await fs.readFile(path.join(inputDir, "open_gaps.json"), "utf8"));

const workbook = Workbook.create();

const summarySheet = workbook.worksheets.add("Ozet");
summarySheet.getRange("A1:D14").values = [
  ["Backtest ve Coverage Raporu", null, null, null],
  ["Run ID", summary.run_id, "Konfig", summary.config_name],
  ["Ilk Ay", summary.first_month, "Son Ay", summary.last_month],
  ["Ay Sayisi", summary.month_count, "Pozisyon Sayisi", summary.position_count],
  ["Pozisyonlu Ay", summary.months_with_positions, "Bos Ay", summary.empty_months],
  ["Baslangic Sermayesi", summary.initial_capital, "Bitis Sermayesi", summary.ending_capital],
  ["Toplam Getiri", summary.total_return, "Ortalama Aylik Getiri", summary.avg_monthly_return],
  ["Median Aylik Getiri", summary.median_monthly_return, "En Iyi Ay", summary.best_month_return],
  ["En Kotu Ay", summary.worst_month_return, "Secilen Sembol", summary.unique_symbol_count],
  ["Acik Gapli Secim", summary.positions_with_open_gap, "Tam Temiz Secim", summary.positions_without_open_gap],
  ["Acik Gap Orani", summary.open_gap_position_ratio, "Secimde Yuksek Guven", summary.high_confidence_positions],
  ["Orta Guven Secim", summary.medium_confidence_positions, "Dusuk Guven Secim", summary.low_confidence_positions],
  ["Rapor Notu", "Acik gap sayisi, sembolun bugun itibariyla kalan post-listing announcement date eksigini gosterir.", null, null],
  ["Yorum", "Backtest secimleri kullanilabilir; coverage sayfasi secimlerin ne kadar temiz oldugunu ay bazinda gosterir.", null, null],
];
summarySheet.getRange("A1:D14").format = {
  font: { name: "Calibri", size: 11, color: "#1F1F1F" },
  verticalAlignment: "center",
  wrapText: true,
};
summarySheet.getRange("A1:D1").merge();
summarySheet.getRange("A1:D1").format = {
  fill: { type: "solid", color: "#1F4E78" },
  font: { color: "#FFFFFF", bold: true, size: 14, name: "Calibri" },
};
summarySheet.getRange("A2:A14").format = {
  fill: { type: "solid", color: "#D9EAF7" },
  font: { bold: true, name: "Calibri", size: 11, color: "#1F1F1F" },
};
summarySheet.getRange("C2:C12").format = {
  fill: { type: "solid", color: "#D9EAF7" },
  font: { bold: true, name: "Calibri", size: 11, color: "#1F1F1F" },
};
summarySheet.getRange("B5:D12").format.numberFormat = "#,##0.00";
summarySheet.getRange("B7:D8").format.numberFormat = "0.00%";
summarySheet.getRange("B10:D11").format.numberFormat = "0.00%";
summarySheet.getRange("A:A").format.columnWidthPx = 180;
summarySheet.getRange("B:B").format.columnWidthPx = 250;
summarySheet.getRange("C:C").format.columnWidthPx = 180;
summarySheet.getRange("D:D").format.columnWidthPx = 180;
summarySheet.freezePanes.freezeRows(1);

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

const positionsSheet = writeRecordsSheet(
  workbook,
  "Secilen Pozisyonlar",
  selected,
  [
    { key: "month", header: "Ay" },
    { key: "symbol", header: "Sembol" },
    { key: "score", header: "Skor", numberFormat: "0.000000" },
    { key: "x1", header: "X1", numberFormat: "0.000000" },
    { key: "x2", header: "X2", numberFormat: "0.000000" },
    { key: "used_period_end", header: "Kullanilan Donem" },
    { key: "used_announcement_date", header: "Aciklama Tarihi" },
    { key: "buy_date", header: "Alis" },
    { key: "buy_price", header: "Alis Fiyati", numberFormat: "#,##0.0000" },
    { key: "sell_date", header: "Satis" },
    { key: "sell_price", header: "Satis Fiyati", numberFormat: "#,##0.0000" },
    { key: "net_return", header: "Net Getiri", numberFormat: "0.00%" },
    { key: "universe_confidence", header: "Universe Guveni" },
  ],
  { freezeColumns: 2 },
);
positionsSheet.getRange("A:M").format.columnWidthPx = 110;

const coverageSheet = writeRecordsSheet(
  workbook,
  "Secilen Coverage",
  selectedCoverage,
  [
    { key: "month", header: "Ay" },
    { key: "symbol", header: "Sembol" },
    { key: "used_period_end", header: "Kullanilan Donem" },
    { key: "used_announcement_date", header: "Aciklama Tarihi" },
    { key: "announcement_age_days", header: "Duyuru Yasi (gun)" },
    { key: "listing_gap_class", header: "Coverage Sinifi" },
    { key: "post_listing_fetch_gap_count", header: "Kalan Gercek Gap" },
    { key: "pre_listing_expected_gap_count", header: "Pre-listing Gap" },
    { key: "first_missing_period", header: "Ilk Kalan Bosluk" },
    { key: "last_missing_period", header: "Son Kalan Bosluk" },
    { key: "selection_gap_flag", header: "Durum" },
    { key: "universe_confidence", header: "Universe Guveni" },
  ],
  { freezeColumns: 2 },
);
coverageSheet.getRange("A:L").format.columnWidthPx = 130;

const monthlyCoverageSheet = writeRecordsSheet(
  workbook,
  "Aylik Coverage",
  monthlyCoverage,
  [
    { key: "month", header: "Ay" },
    { key: "selected_count", header: "Secilen Adet", numberFormat: "0" },
    { key: "open_gap_symbol_count", header: "Acik Gapli Sembol", numberFormat: "0" },
    { key: "clean_symbol_count", header: "Temiz Sembol", numberFormat: "0" },
    { key: "open_gap_position_ratio", header: "Acik Gap Orani", numberFormat: "0.00%" },
    { key: "avg_post_listing_gap_count", header: "Ort Kalan Gap", numberFormat: "0.00" },
    { key: "max_post_listing_gap_count", header: "Maks Kalan Gap", numberFormat: "0" },
    { key: "symbols_with_open_gaps", header: "Acik Gapli Semboller" },
  ],
  { freezeColumns: 1 },
);
monthlyCoverageSheet.getRange("A:H").format.columnWidthPx = 130;

const gapSheet = writeRecordsSheet(
  workbook,
  "Kalan Gapler",
  openGaps,
  [
    { key: "symbol", header: "Sembol" },
    { key: "post_listing_fetch_gap_count", header: "Gercek Gap", numberFormat: "0" },
    { key: "pre_listing_expected_gap_count", header: "Pre-listing Gap", numberFormat: "0" },
    { key: "missing_periods_2019_plus", header: "Toplam Bosluk", numberFormat: "0" },
    { key: "first_missing_period", header: "Ilk Bosluk" },
    { key: "last_missing_period", header: "Son Bosluk" },
    { key: "listing_gap_class", header: "Sinif" },
  ],
  { freezeColumns: 1 },
);
gapSheet.getRange("A:G").format.columnWidthPx = 140;

await workbook.inspect({
  kind: "table",
  range: "Ozet!A1:D14",
  include: "values",
  tableMaxRows: 20,
  tableMaxCols: 4,
});

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
