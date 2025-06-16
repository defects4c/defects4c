

*/30 * * * * find /out/**/logs -maxdepth 1 -type f -name '*.log' -size +10M   -exec truncate --size 0 {} +
*/30 * * * * find /out/**/logs -maxdepth 1 -type f -name '*.msg' -size +10M   -exec truncate --size 0 {} +

