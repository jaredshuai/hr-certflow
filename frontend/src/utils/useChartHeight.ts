import { useEffect, useState } from 'react';

/**
 * 根据视口宽度返回合适的图表高度。
 * - 宽屏（>= 900px）使用 defaultHeight
 * - 窄屏使用 mobileHeight
 */
export function useChartHeight(defaultHeight = 280, mobileHeight = 220): number {
  const [height, setHeight] = useState(defaultHeight);

  useEffect(() => {
    function update() {
      setHeight(window.innerWidth < 900 ? mobileHeight : defaultHeight);
    }

    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, [defaultHeight, mobileHeight]);

  return height;
}
