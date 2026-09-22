// Writes the output bundle to disk.
//
// Every file is written to a scratch name and renamed into place, so an
// interrupted run leaves either the previous state or the finished file,
// never a half-written document.json that a downstream job would happily
// read. Scratch names left behind by a failure are removed before the
// error is reported.
#ifndef PUBIR_BUNDLE_H
#define PUBIR_BUNDLE_H

#include <string>

#include "limits.h"
#include "model.h"

namespace pubir {

struct WriteResult {
  bool ok = false;
  std::string errorCode;
  std::string errorMessage;
};

// `force` allows writing into a directory that already holds entries.
// Without it, a non-empty output directory is refused: overwriting one
// run's bundle with another's silently mixes two documents' assets.
WriteResult writeBundle(const Document &doc, const Limits &limits, const std::string &outputDir,
                        const std::string &status, bool force,
                        const std::string &failureCode = std::string(),
                        const std::string &failureMessage = std::string());

} // namespace pubir

#endif
