// Quick and dirty helper script to create the license overview page in markdown for the remote-ui.
//
// Usage:
// pip-licenses --with-description --with-urls \
//   --with-license-file --no-license-path \
//   --with-notice-file \
//   --format=json > licenses.json
// node transform-pip-licenses.js licenses.json licenses.md

const fs = require("fs");

function ensureFileExists(file) {
    if (!fs.existsSync(file)) {
        console.error(`File does not exist: ${file}`);
        process.exit(1);
    }
}

if (process.argv.length < 4) {
    console.error("Expected two argument: <licenses.json> <output.md>");
    process.exit(1);
}

const licenseFile = process.argv[2];
const outputFile = process.argv[3];

ensureFileExists(licenseFile);

const licenses = JSON.parse(fs.readFileSync(licenseFile, "utf-8"));

fs.writeFileSync(outputFile, fs.readFileSync("templates/licenses-header.md", "utf-8"), "utf-8");

for (const index in licenses) {
    let package = licenses[index];
    let name = package.Name;
    let repository = package.URL;
    let license = package.License;
    let version = package.Version;

    console.log(`${name} ${version}: ${license}`);

    fs.appendFileSync(outputFile, `#### ${name} ${version}\n`, "utf-8");
    fs.appendFileSync(outputFile, `${package.Description}  \n`, "utf-8");
    fs.appendFileSync(outputFile, `License: ${license}  \n`, "utf-8");
    if (repository) {
        fs.appendFileSync(outputFile, `This software may be included in this product and a copy of the source code may be downloaded from: ${repository}.\n`, "utf-8");
    }

    fs.appendFileSync(outputFile, "```\n", "utf-8");
    fs.appendFileSync(outputFile, `${package.LicenseText.trim()}`, "utf-8");
    fs.appendFileSync(outputFile, "\n```\n\n", "utf-8");
}

fs.appendFileSync(outputFile, fs.readFileSync("templates/licenses-footer.md", "utf-8"), "utf-8");
