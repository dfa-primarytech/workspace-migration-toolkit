// publisher-parser: .pub -> intermediate representation.
//
//   publisher-parser input.pub output/
//
// Produces output/document.json, output/assets.json, output/report.json and
// output/assets/<sha256>.<ext>.
//
// The bundle is the deliverable and is deliberately kept. Scratch files are
// not: see bundle.cpp.
#include <libmspub/libmspub.h>
#include <librevenge-stream/librevenge-stream.h>

#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include "bundle.h"
#include "collector.h"
#include "limits.h"
#include "model.h"
#include "serialise.h"
#include "sha256.h"

namespace {

// OLE2 compound file magic. Publisher files are OLE containers; libmspub
// does the real validation, but recognising the container cheaply lets the
// report say what the file actually was when parsing fails.
const unsigned char kOle2Magic[8] = {0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1};

void usage() {
  std::fprintf(stderr,
               "usage: publisher-parser [options] <input.pub> <output-directory>\n"
               "\n"
               "Options:\n"
               "  --force                 write into a non-empty output directory\n"
               "  --max-input-bytes N     refuse inputs larger than N bytes\n"
               "  --max-seconds S         collection time budget (a backstop; the caller must\n"
               "                          also impose a hard subprocess timeout)\n"
               "  --max-callbacks N       maximum collected callbacks\n"
               "  --max-pages N           maximum collected pages\n"
               "  --max-elements N        maximum collected elements\n"
               "  --max-assets N          maximum distinct extracted assets\n"
               "  --max-asset-bytes N     maximum bytes for a single asset\n"
               "  --max-total-asset-bytes N  maximum bytes across all assets\n"
               "  --max-text-bytes N      maximum collected text bytes\n"
               "  --version               print the parser and library versions\n"
               "  --help                  print this message\n");
}

std::string basename(const std::string &path) {
  const std::size_t slash = path.find_last_of('/');
  return slash == std::string::npos ? path : path.substr(slash + 1);
}

bool parseLongLong(const char *text, long long &out) {
  if (text == nullptr || *text == '\0') return false;
  char *end = nullptr;
  const long long value = std::strtoll(text, &end, 10);
  if (end == nullptr || *end != '\0' || value <= 0) return false;
  out = value;
  return true;
}

// Writes a bundle for an input that never reached a model, so a caller
// always has a machine-readable answer rather than only an exit code.
int failEarly(const pubir::Document &doc, const pubir::Limits &limits,
              const std::string &outputDir, bool force, const char *code, const char *message) {
  // The message is a fixed string chosen here, never anything read out of
  // the document, so a hostile file cannot write its own text into a log.
  std::fprintf(stderr, "publisher-parser: %s: %s\n", code, message);
  const pubir::WriteResult written =
      pubir::writeBundle(doc, limits, outputDir, "failed", force, code, message);
  if (!written.ok) {
    std::fprintf(stderr, "publisher-parser: %s: %s\n", written.errorCode.c_str(),
                 written.errorMessage.c_str());
  }
  return 2;
}

} // namespace

int main(int argc, char **argv) {
  pubir::Limits limits;
  bool force = false;
  std::vector<std::string> positional;

  for (int i = 1; i < argc; i++) {
    const std::string arg(argv[i]);
    if (arg == "--help" || arg == "-h") {
      usage();
      return 0;
    }
    if (arg == "--version") {
      std::printf("%s %s\n", pubir::kGeneratorName, pubir::kGeneratorVersion);
      std::printf("schema %s\n", pubir::kSchemaVersion);
        // libmspub and librevenge expose no version macro, so the versions
      // the binary was built against are baked in by CMake from pkg-config.
      std::printf("libmspub %s\n", PUBIR_LIBMSPUB_VERSION);
      std::printf("librevenge %s\n", PUBIR_LIBREVENGE_VERSION);
      return 0;
    }
    if (arg == "--force") {
      force = true;
      continue;
    }

    auto needsValue = [&](const char *name, long long &target) -> bool {
      if (arg != name) return false;
      if (i + 1 >= argc || !parseLongLong(argv[i + 1], target)) {
        std::fprintf(stderr, "publisher-parser: %s needs a positive integer\n", name);
        std::exit(2);
      }
      i++;
      return true;
    };
    if (needsValue("--max-input-bytes", limits.maxInputBytes)) continue;
    if (needsValue("--max-callbacks", limits.maxCallbacks)) continue;
    if (needsValue("--max-pages", limits.maxPages)) continue;
    if (needsValue("--max-elements", limits.maxElements)) continue;
    if (needsValue("--max-assets", limits.maxAssets)) continue;
    if (needsValue("--max-asset-bytes", limits.maxAssetBytes)) continue;
    if (needsValue("--max-total-asset-bytes", limits.maxTotalAssetBytes)) continue;
    if (needsValue("--max-text-bytes", limits.maxTextBytes)) continue;
    if (arg == "--max-seconds") {
      long long seconds = 0;
      if (i + 1 >= argc || !parseLongLong(argv[i + 1], seconds)) {
        std::fprintf(stderr, "publisher-parser: --max-seconds needs a positive integer\n");
        return 2;
      }
      limits.maxSeconds = static_cast<double>(seconds);
      i++;
      continue;
    }
    if (!arg.empty() && arg[0] == '-') {
      std::fprintf(stderr, "publisher-parser: unknown option %s\n", arg.c_str());
      usage();
      return 2;
    }
    positional.push_back(arg);
  }

  if (positional.size() != 2) {
    usage();
    return 2;
  }
  const std::string inputPath = positional[0];
  const std::string outputDir = positional[1];

  pubir::Document doc;
  // Only the basename reaches the bundle. The directory a file was
  // processed in is often a person's name on a school machine, and the
  // bundle is meant to be shareable with whoever reviews the conversion.
  doc.sourceFilename = basename(inputPath);

  std::ifstream input(inputPath, std::ios::binary | std::ios::ate);
  if (!input) {
    return failEarly(doc, limits, outputDir, force, "input-unreadable",
                     "the input file could not be opened");
  }
  const std::streamoff size = input.tellg();
  if (size < 0) {
    return failEarly(doc, limits, outputDir, force, "input-unreadable",
                     "the input file size could not be determined");
  }
  if (static_cast<long long>(size) > limits.maxInputBytes) {
    doc.sourceByteLength = static_cast<long long>(size);
    return failEarly(doc, limits, outputDir, force, "input-too-large",
                     "the input file is larger than the configured limit");
  }
  if (size == 0) {
    return failEarly(doc, limits, outputDir, force, "input-empty", "the input file is empty");
  }

  std::string bytes;
  bytes.resize(static_cast<std::size_t>(size));
  input.seekg(0);
  input.read(&bytes[0], size);
  if (!input) {
    return failEarly(doc, limits, outputDir, force, "input-unreadable",
                     "the input file could not be read in full");
  }
  input.close();

  doc.sourceByteLength = static_cast<long long>(bytes.size());
  doc.sourceSha256 = pubir::Sha256::of(bytes);
  doc.containerType = (bytes.size() >= sizeof(kOle2Magic) &&
                       std::memcmp(bytes.data(), kOle2Magic, sizeof(kOle2Magic)) == 0)
                          ? "ole2"
                          : "unknown";

  librevenge::RVNGStringStream stream(reinterpret_cast<const unsigned char *>(bytes.data()),
                                      static_cast<unsigned int>(bytes.size()));

  // Container validation is libmspub's job, not ours: it walks the OLE
  // directory and the Publisher streams. Anything it refuses, we refuse.
  if (!libmspub::MSPUBDocument::isSupported(&stream)) {
    doc.supportedByParser = false;
    return failEarly(doc, limits, outputDir, force, "unsupported-document",
                     "libmspub does not recognise this file as a Publisher document");
  }
  doc.supportedByParser = true;
  // libmspub's public API exposes no version accessor, so the family is as
  // specific as this parser can honestly be.
  doc.formatFamily = "microsoft-publisher";

  pubir::IrCollector collector(limits);
  collector.setSource(doc.sourceFilename, doc.sourceSha256, doc.sourceByteLength, doc.containerType,
                      doc.formatFamily);
  collector.setSupported(true);

  stream.seek(0, librevenge::RVNG_SEEK_SET);
  const bool parsed = libmspub::MSPUBDocument::parse(&stream, &collector);
  const pubir::Document &model = collector.finish();

  if (!parsed) {
    const pubir::WriteResult written =
        pubir::writeBundle(model, limits, outputDir, "failed", force, "parse-failed",
                           "libmspub reported a parse failure; any content collected before the "
                           "failure is included in this bundle");
    if (!written.ok) {
      std::fprintf(stderr, "publisher-parser: %s: %s\n", written.errorCode.c_str(),
                   written.errorMessage.c_str());
      return 2;
    }
    std::fprintf(stderr, "publisher-parser: parse-failed: libmspub could not parse this document\n");
    return 1;
  }

  const std::string status = model.truncated ? "truncated" : "ok";
  const pubir::WriteResult written = pubir::writeBundle(model, limits, outputDir, status, force);
  if (!written.ok) {
    std::fprintf(stderr, "publisher-parser: %s: %s\n", written.errorCode.c_str(),
                 written.errorMessage.c_str());
    return 2;
  }

  // Counts only. Nothing from the document's text or images is ever
  // printed: this output goes to logs.
  std::printf("pages=%lld elements=%lld assets=%lld fonts=%lld callbacks=%lld status=%s\n",
              model.counts.pages, model.counts.elements, model.counts.assets, model.counts.fonts,
              model.callbackTotal, status.c_str());
  return model.truncated ? 3 : 0;
}
