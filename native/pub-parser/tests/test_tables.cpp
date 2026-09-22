#include "testing.h"

#include "fixtures.h"

using namespace pubir;
using namespace fixtures;

namespace {

RVNGPropertyList tableWithColumns(const std::vector<double> &widthsInches) {
  librevenge::RVNGPropertyListVector columns;
  for (double width : widthsInches) {
    RVNGPropertyList column;
    column.insert("style:column-width", width, librevenge::RVNG_INCH);
    columns.append(column);
  }
  RVNGPropertyList props = box(1, 1, 4, 3);
  props.insert("librevenge:table-columns", columns);
  return props;
}

RVNGPropertyList row(double heightInches) {
  RVNGPropertyList props;
  props.insert("style:row-height", heightInches, librevenge::RVNG_INCH);
  return props;
}

RVNGPropertyList cell(int rowIndex, int column, int rowSpan = 1, int columnSpan = 1) {
  RVNGPropertyList props;
  props.insert("librevenge:row", rowIndex);
  props.insert("librevenge:column", column);
  if (rowSpan != 1) props.insert("table:number-rows-spanned", rowSpan);
  if (columnSpan != 1) props.insert("table:number-columns-spanned", columnSpan);
  return props;
}

const Element &firstTable(const Document &doc) {
  static Element empty;
  const auto tables = elementsOfType(doc, "table");
  return tables.empty() ? empty : *tables[0];
}

} // namespace

TEST(tables_preserve_geometry_and_column_widths) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startTableObject(tableWithColumns({2.0, 1.5}));
  collector.openTableRow(row(0.5));
  collector.openTableCell(cell(0, 0));
  collector.closeTableCell();
  collector.openTableCell(cell(0, 1));
  collector.closeTableCell();
  collector.closeTableRow();
  collector.endTableObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  const Element &table = firstTable(doc);
  CHECK(table.bounds.valid);
  CHECK_NEAR(table.bounds.width, 288.0, 1e-6);
  CHECK_EQ(table.table.columnWidths.size(), std::size_t(2));
  CHECK_NEAR(table.table.columnWidths[0].points, 144.0, 1e-6);
  CHECK_NEAR(table.table.columnWidths[1].points, 108.0, 1e-6);
  CHECK_EQ(table.table.rows.size(), std::size_t(1));
  CHECK_NEAR(table.table.rows[0].height.points, 36.0, 1e-6);
  CHECK(!table.table.rows[0].heightIsMinimum);
}

TEST(tables_fall_back_to_the_minimum_row_height) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startTableObject(tableWithColumns({2.0}));
  RVNGPropertyList minimum;
  minimum.insert("style:min-row-height", 0.25, librevenge::RVNG_INCH);
  collector.openTableRow(minimum);
  collector.closeTableRow();
  collector.endTableObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  const TableRow &only = firstTable(doc).table.rows[0];
  CHECK(only.height.valid);
  CHECK_NEAR(only.height.points, 18.0, 1e-6);
  CHECK(only.heightIsMinimum);
}

TEST(tables_record_spans_and_covered_cells) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startTableObject(tableWithColumns({2.0, 2.0}));
  collector.openTableRow(row(0.5));
  collector.openTableCell(cell(0, 0, 1, 2));
  collector.closeTableCell();
  collector.insertCoveredTableCell(cell(0, 1));
  collector.closeTableRow();
  collector.endTableObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  const TableRow &only = firstTable(doc).table.rows[0];
  CHECK_EQ(only.cells.size(), std::size_t(2));
  CHECK_EQ(only.cells[0].columnSpan, 2);
  CHECK(!only.cells[0].covered);
  // The covered cell holds nothing, but dropping it would leave the row's
  // coordinates inconsistent with the column count.
  CHECK(only.cells[1].covered);
  CHECK_EQ(only.cells[1].column, 1);
}

TEST(tables_keep_paragraphs_and_runs_inside_cells) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startTableObject(tableWithColumns({2.0}));
  collector.openTableRow(row(0.5));
  collector.openTableCell(cell(0, 0));
  collector.openParagraph(RVNGPropertyList());
  collector.openSpan(span("Calibri", 11.0, true));
  collector.insertText(librevenge::RVNGString("Autumn term"));
  collector.closeSpan();
  collector.closeParagraph();
  collector.closeTableCell();
  collector.closeTableRow();
  collector.endTableObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  const TableCell &only = firstTable(doc).table.rows[0].cells[0];
  CHECK_EQ(only.paragraphs.size(), std::size_t(1));
  CHECK_EQ(only.paragraphs[0].runs[0].text, std::string("Autumn term"));
  CHECK(only.paragraphs[0].runs[0].bold);
}

TEST(tables_single_column_three_row_shape_is_recovered) {
  // The shape the first real fixture is expected to contain.
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(5.8268, 8.2677));
  collector.startTableObject(tableWithColumns({3.0}));
  for (int r = 0; r < 3; r++) {
    collector.openTableRow(row(0.4));
    collector.openTableCell(cell(r, 0));
    collector.openParagraph(RVNGPropertyList());
    collector.openSpan(span("SassoonPrimaryType", 12.0));
    collector.insertText(librevenge::RVNGString("row"));
    collector.closeSpan();
    collector.closeParagraph();
    collector.closeTableCell();
    collector.closeTableRow();
  }
  collector.endTableObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  const Element &table = firstTable(doc);
  CHECK_EQ(table.table.columnWidths.size(), std::size_t(1));
  CHECK_EQ(table.table.rows.size(), std::size_t(3));
  CHECK_EQ(doc.counts.paragraphs, 3LL);
  CHECK_EQ(doc.counts.tableElements, 1LL);
}

TEST(tables_report_a_row_that_arrives_without_a_table) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.openTableRow(row(0.5));
  collector.openTableCell(cell(0, 0));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK(hasDiagnostic(doc, "row-without-table"));
  CHECK(hasDiagnostic(doc, "cell-without-row"));
  CHECK_EQ(doc.callbackCounts.at("openTableRow"), 1LL);
}

TEST(tables_without_declared_columns_are_flagged) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startTableObject(box(1, 1, 4, 3));
  collector.endTableObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK(hasWarning(firstTable(doc), "table-columns-unknown"));
}
