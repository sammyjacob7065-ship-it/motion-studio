import { loadFont as inter } from '@remotion/google-fonts/Inter';
import { loadFont as poppins } from '@remotion/google-fonts/Poppins';
import { loadFont as montserrat } from '@remotion/google-fonts/Montserrat';
import { loadFont as spaceGrotesk } from '@remotion/google-fonts/SpaceGrotesk';
import { loadFont as playfair } from '@remotion/google-fonts/PlayfairDisplay';
import { loadFont as bebas } from '@remotion/google-fonts/BebasNeue';
import { loadFont as oswald } from '@remotion/google-fonts/Oswald';
import { loadFont as dmSans } from '@remotion/google-fonts/DMSans';
import { loadFont as outfit } from '@remotion/google-fonts/Outfit';
import { loadFont as sora } from '@remotion/google-fonts/Sora';
import { loadFont as anton } from '@remotion/google-fonts/Anton';

const W = (...w: string[]) => ({ weights: w as any, subsets: ['latin'] as any });
const LOADERS: Record<string, () => { fontFamily: string }> = {
  inter: () => inter('normal', W('400', '500', '600', '700', '800', '900')),
  poppins: () => poppins('normal', W('400', '500', '600', '700', '800')),
  montserrat: () => montserrat('normal', W('400', '500', '600', '700', '800', '900')),
  spacegrotesk: () => spaceGrotesk('normal', W('400', '500', '600', '700')),
  playfairdisplay: () => playfair('normal', W('400', '600', '700', '800')),
  bebasneue: () => bebas('normal', W('400')),
  oswald: () => oswald('normal', W('400', '500', '600', '700')),
  dmsans: () => dmSans('normal', W('400', '500', '700')),
  outfit: () => outfit('normal', W('400', '500', '600', '700', '800')),
  sora: () => sora('normal', W('400', '600', '700', '800')),
  anton: () => anton('normal', W('400')),
};
export const FONT_NAMES = ['Inter', 'Poppins', 'Montserrat', 'Space Grotesk', 'Playfair Display', 'Bebas Neue', 'Oswald', 'DM Sans', 'Outfit', 'Sora', 'Anton'];

const cache: Record<string, string> = {};
export function fontFamily(name?: string): string {
  const key = String(name || 'inter').toLowerCase().replace(/[^a-z]/g, '');
  const k = LOADERS[key] ? key : 'inter';
  if (!cache[k]) cache[k] = LOADERS[k]().fontFamily;
  return cache[k] + ', Inter, Arial, sans-serif';
}
