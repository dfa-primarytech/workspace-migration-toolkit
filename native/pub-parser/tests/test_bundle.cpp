#include "testing.h"

#include <cstdio>
#include <cstdlib>
#include <dirent.h>
#include <fstream>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

#include "bundle.h"
#include "fixtures.h"

using namespace pubir;
using namespace fixtures;

namespace {

// A scratch directory that removes itself, so a failing test cannot leave
// extracted payloads behind.
class TempDir {
public:
  TempDir() {
    std::string pattern = "/tmp/pubir-test-XXXXXX";
    std::vector<char> buffer(pattern.begin(), pattern.end());
    buffer.push_back('\0');
    const char *made = ::mkdtemp(buffer.data());
    path_ = made == nullptr ? std::string() : std::string(made);
  }
  ~TempDir() { removeAll(path_); }

  const std::string &path() const { return path_; }

private:
  static void removeAll(const std::string &path) {
    if (path.empty()) return;
    DIR *dir = ::opendir(path.c_str());
    if (dir != nullptr) {
      while (struct dirent *entry = ::readdir(dir)) {
        const std::string name(entry->d_name);
        if (name == "." || name == "..") continue;
        const std::string child = path + "/" + name;
        struct stat st;
        if (::stat(child.c_str(), &st) == 0 && S_ISDIR(st.st_mode)) removeAll(child);
        else ::unlink(child.c_str());
      }
      ::closedir(dir);
    }
    ::rmdir(path.c_str());
  }

  std::string path_;
};

bool fileExists(const std::string &path) {
  struct stat st;
  return ::stat(path.c_str(), &st) == 0 && S_ISREG(st.st_mode);
}

std::string readFile(const std::string &path) {
  std::ifstream in(path, std::ios::binary);
  std::ostringstream buffer;
  buffer << in.rdbuf();
  return buffer.str();
}

std::vector<std::string> listDir(const std::string &path) {
  std::vector<std::string> names;
  DIR *dir = ::opendir(path.c_str());
  if (dir == nullptr) return names;
  while (struct dirent *entry = ::readdir(dir)) {
    const std::string name(entry->d_name);
    if (name == "." || name == "..") continue;
    names.push_back(name);
  }
  ::closedir(dir);
  return names;
}

Document sampleDocument() {
  IrCollector collector;
  collector.setSource("example.pub", std::string(64, 'a'), 1024, "ole2", "microsoft-publisher");
  collector.setSupported(true);
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(5.8268, 8.2677));
  collector.setStyle(bitmapFill(tinyPng(0x44)));
  collector.drawPolygon(rectanglePolygon(1, 1, 2, 2));
  collector.startTextObject(box(0.5, 0.5, 4, 1));
  collector.openParagraph(RVNGPropertyList());
  collector.openSpan(span("Calibri", 12.0));
  collector.insertText(librevenge::RVNGString("Newsletter"));
  collector.closeSpan();
  collector.closeParagraph();
  collector.endTextObject();
  collector.endPage();
  collector.endDocument();
  return collector.finish();
}

} // namespace

TEST(bundle_writes_the_three_documents_and_the_assets) {
  TempDir dir;
  CHECK(!dir.path().empty());
  const Document doc = sampleDocument();
  const std::string out = dir.path() + "/bundle";

  const WriteResult result = writeBundle(doc, Limits(), out, "ok", false);
  CHECK(result.ok);
  CHECK(fileExists(out + "/document.json"));
  CHECK(fileExists(out + "/assets.json"));
  CHECK(fileExists(out + "/report.json"));
  CHECK_EQ(doc.assets.size(), std::size_t(1));
  CHECK(fileExists(out + "/" + doc.assets[0].filename));
}

TEST(bundle_asset_filenames_come_from_the_content_hash) {
  TempDir dir;
  const Document doc = sampleDocument();
  const std::string out = dir.path() + "/bundle";
  CHECK(writeBundle(doc, Limits(), out, "ok", false).ok);

  const std::vector<std::string> names = listDir(out + "/assets");
  CHECK_EQ(names.size(), std::size_t(1));
  // Nothing from the document chooses a path: 64 hex characters plus an
  // extension the parser picked from the payload's own signature.
  CHECK_EQ(names[0], doc.assets[0].sha256 + ".png");
  CHECK_EQ(readFile(out + "/assets/" + names[0]), tinyPng(0x44));
}

TEST(bundle_refuses_a_non_empty_output_directory_without_force) {
  TempDir dir;
  const Document doc = sampleDocument();
  const std::string out = dir.path() + "/bundle";
  CHECK(writeBundle(doc, Limits(), out, "ok", false).ok);

  const WriteResult second = writeBundle(doc, Limits(), out, "ok", false);
  CHECK(!second.ok);
  CHECK_EQ(second.errorCode, std::string("output-not-empty"));

  const WriteResult forced = writeBundle(doc, Limits(), out, "ok", true);
  CHECK(forced.ok);
}

TEST(bundle_refuses_an_output_path_that_is_a_file) {
  TempDir dir;
  const std::string path = dir.path() + "/not-a-directory";
  { std::ofstream(path) << "x"; }

  const WriteResult result = writeBundle(sampleDocument(), Limits(), path, "ok", false);
  CHECK(!result.ok);
  CHECK_EQ(result.errorCode, std::string("output-not-a-directory"));
}

TEST(bundle_leaves_no_scratch_files_behind) {
  TempDir dir;
  const std::string out = dir.path() + "/bundle";
  CHECK(writeBundle(sampleDocument(), Limits(), out, "ok", false).ok);

  for (const std::string &name : listDir(out)) {
    CHECK(name.find(".tmp-") == std::string::npos);
  }
  for (const std::string &name : listDir(out + "/assets")) {
    CHECK(name.find(".tmp-") == std::string::npos);
  }
}

TEST(bundle_output_is_byte_identical_across_runs) {
  TempDir first;
  TempDir second;
  CHECK(writeBundle(sampleDocument(), Limits(), first.path() + "/b", "ok", false).ok);
  CHECK(writeBundle(sampleDocument(), Limits(), second.path() + "/b", "ok", false).ok);

  // No timestamps, no paths, no iteration-order dependence: two runs over
  // the same input have to produce the same bytes or nothing downstream
  // can diff one conversion against another.
  for (const char *name : {"document.json", "assets.json", "report.json"}) {
    CHECK_EQ(readFile(first.path() + "/b/" + name), readFile(second.path() + "/b/" + name));
  }
}

TEST(bundle_report_records_status_and_failure_codes) {
  TempDir dir;
  const std::string out = dir.path() + "/bundle";
  CHECK(writeBundle(Document(), Limits(), out, "failed", false, "input-too-large",
                    "the input file is larger than the configured limit")
            .ok);

  const std::string report = readFile(out + "/report.json");
  CHECK(report.find("\"status\": \"failed\"") != std::string::npos);
  CHECK(report.find("\"failureCode\": \"input-too-large\"") != std::string::npos);
}

TEST(bundle_document_json_carries_the_source_facts_and_no_binary) {
  TempDir dir;
  const std::string out = dir.path() + "/bundle";
  const Document doc = sampleDocument();
  CHECK(writeBundle(doc, Limits(), out, "ok", false).ok);

  const std::string document = readFile(out + "/document.json");
  CHECK(document.find("\"filename\": \"example.pub\"") != std::string::npos);
  CHECK(document.find("\"containerType\": \"ole2\"") != std::string::npos);
  CHECK(document.find("\"schemaVersion\": \"1.0.0\"") != std::string::npos);
  // The payload lives in assets/, never inline: a base64 bitmap here would
  // bloat the file past being reviewable and duplicate the asset store.
  CHECK(document.find("\"draw:fill-image\": \"<binary>\"") != std::string::npos);
  CHECK(document.find("iVBOR") == std::string::npos);
}

TEST(bundle_compatibility_is_labelled_a_parser_candidate) {
  TempDir dir;
  const std::string out = dir.path() + "/bundle";
  CHECK(writeBundle(sampleDocument(), Limits(), out, "ok", false).ok);

  // A consumer must not be able to read a parser guess as a verified round
  // trip through Google, so every status says what it is based on.
  CHECK(readFile(out + "/document.json").find("\"basis\": \"parser-candidate\"") !=
        std::string::npos);
  CHECK(readFile(out + "/report.json").find("\"basis\": \"parser-candidate\"") != std::string::npos);
}
