import { useMemo, useState } from "react";

/** Click-a-column-header sorting for plain-JS arrays of objects. No server
 * round-trip needed -- roster/history payloads are small enough to sort
 * client-side once fetched from the backend. */
export function useSortableData(items, initialKey = null, initialDirection = "desc") {
  const [sortKey, setSortKey] = useState(initialKey);
  const [direction, setDirection] = useState(initialDirection);

  const sorted = useMemo(() => {
    if (!sortKey) return items;
    const copy = [...items];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "string") {
        return direction === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return direction === "asc" ? av - bv : bv - av;
    });
    return copy;
  }, [items, sortKey, direction]);

  function requestSort(key) {
    if (key === sortKey) {
      setDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setDirection("desc");
    }
  }

  return { sorted, sortKey, direction, requestSort };
}
