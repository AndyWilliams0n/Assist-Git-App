import { Home, Search, User, WandSparkles, Triangle, Tag, Trash2, Pencil } from 'lucide-react'

type DesignColor = {
  name: string
  hex: string
}

type DesignTypography = {
  headline?: string
  body?: string
  label?: string
}

export type DesignSystemSnapshot = {
  colors?: DesignColor[]
  typography?: DesignTypography
  styleGuidelines?: string
}

type DesignSystemPreviewProps = {
  designSystem: DesignSystemSnapshot | null
  monochrome: boolean
}

const DEFAULT_COLORS: DesignColor[] = [
  { name: 'Primary', hex: '#0066FF' },
  { name: 'Secondary', hex: '#77767A' },
  { name: 'Tertiary', hex: '#9700FF' },
  { name: 'Neutral', hex: '#787677' },
]

const MONOCHROME_COLORS: DesignColor[] = [
  { name: 'Primary', hex: '#68686E' },
  { name: 'Secondary', hex: '#7A7A7F' },
  { name: 'Tertiary', hex: '#8B8B90' },
  { name: 'Neutral', hex: '#9A9A9F' },
]

const normalizeHex = (value: string, fallback: string) => {
  const text = String(value || '').trim()

  if (/^#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?$/.test(text)) {
    return text.toUpperCase()
  }

  return fallback
}

const colorScale = (baseHex: string) =>
  `linear-gradient(90deg, #000000 0%, ${baseHex} 20%, #10204a 35%, #3b64c9 50%, #7192e0 65%, #a6b7e6 80%, #d8d6e3 100%)`

const resolveColors = (designSystem: DesignSystemSnapshot | null, monochrome: boolean): DesignColor[] => {
  if (monochrome) {
    return MONOCHROME_COLORS
  }

  const sourceColors = Array.isArray(designSystem?.colors) ? designSystem.colors : []
  const normalizedColors = sourceColors
    .slice(0, 4)
    .map((item, index) => ({
      name: String(item?.name || DEFAULT_COLORS[index]?.name || `Color ${index + 1}`).trim(),
      hex: normalizeHex(String(item?.hex || ''), DEFAULT_COLORS[index]?.hex || '#77767A'),
    }))

  if (normalizedColors.length === 4) {
    return normalizedColors
  }

  return DEFAULT_COLORS
}

const panelClassName = 'rounded-[22px] border border-[#D6D5DC] bg-[#E5E4E9] p-5'

export function DesignSystemPreview(props: DesignSystemPreviewProps) {
  const { designSystem, monochrome } = props
  const colors = resolveColors(designSystem, monochrome)
  const primaryColor = colors[0]?.hex || '#0066FF'
  const secondaryColor = colors[1]?.hex || '#77767A'
  const tertiaryColor = colors[2]?.hex || '#9700FF'
  const neutralColor = colors[3]?.hex || '#787677'
  const headlineText = String(designSystem?.typography?.headline || '').trim() || 'Headline'
  const bodyText = String(designSystem?.typography?.body || '').trim() || 'Body'
  const labelText = String(designSystem?.typography?.label || '').trim() || 'Label'
  const activePrimary = monochrome ? '#66666D' : primaryColor
  const activeTertiary = monochrome ? '#78787F' : tertiaryColor
  const activeNeutral = monochrome ? '#7B7B82' : secondaryColor
  const navContainerBg = '#DDDCE1'

  return (
    <section className='rounded-[28px] border-[3px] border-[#5A62F2] bg-[#E2E1E6] p-4'>
      <div className='grid gap-3 lg:grid-cols-[290px_1fr]'>
        <div className='grid grid-cols-1 gap-3'>
          {colors.map((color, index) => (
            <div key={`${color.name}-${color.hex}`} className='overflow-hidden rounded-[20px] border border-[#CFCED5]'>
              <div
                className='flex items-center justify-between px-4 py-2 text-[30px] text-white md:text-sm'
                style={{ backgroundColor: monochrome ? '#6D6D73' : color.hex }}
              >
                <span className='font-medium'>{color.name}</span>

                <span className='font-semibold'>{normalizeHex(color.hex, DEFAULT_COLORS[index]?.hex || '#77767A')}</span>
              </div>

              <div className='h-12' style={{ background: colorScale(monochrome ? '#727279' : color.hex) }} />
            </div>
          ))}
        </div>

        <div className='grid grid-cols-1 gap-3 md:grid-cols-6 xl:grid-cols-12'>
          <div className={`${panelClassName} md:col-span-2 xl:col-span-4`}>
            <p className='text-sm text-[#8B8A91]'>{headlineText}</p>

            <p className='text-[108px] leading-none text-[#48474F]'>Aa</p>
          </div>

          <div className={`${panelClassName} md:col-span-2 xl:col-span-4`}>
            <div className='grid grid-cols-2 gap-2 text-[31px] md:text-sm'>
              <button
                className='rounded border border-transparent px-4 py-2 text-white'
                type='button'
                style={{ backgroundColor: activePrimary }}
              >
                Primary
              </button>

              <button className='rounded border border-[#B8B7BF] bg-transparent px-4 py-2 text-[#75747A]' type='button'>
                Secondary
              </button>

              <button className='rounded border border-black bg-black px-4 py-2 text-white' type='button'>
                Inverted
              </button>

              <button className='rounded border border-[#9A99A1] bg-transparent px-4 py-2 text-[#67666D]' type='button'>
                Outlined
              </button>
            </div>
          </div>

          <div className={`${panelClassName} md:col-span-2 xl:col-span-4`}>
            <div className='flex items-center gap-3 rounded border border-[#B8B7BF] bg-transparent px-4 py-3 text-[#7B7A80]'>
              <Search className='h-5 w-5' />

              <span className='text-[32px] md:text-sm'>Search</span>
            </div>
          </div>

          <div className={`${panelClassName} md:col-span-2 xl:col-span-4`}>
            <p className='text-sm text-[#8B8A91]'>{bodyText}</p>

            <p className='text-[108px] leading-none text-[#76757C]'>Aa</p>
          </div>

          <div className={`${panelClassName} md:col-span-2 xl:col-span-4`}>
            <div className='space-y-4 pt-6'>
              <div className='h-2.5 rounded-sm' style={{ backgroundColor: activePrimary }} />

              <div className='h-2.5 rounded-sm' style={{ backgroundColor: activeNeutral }} />

              <div className='h-2.5 w-2/3 rounded-sm' style={{ backgroundColor: activeTertiary }} />
            </div>
          </div>

          <div className={`${panelClassName} md:col-span-2 xl:col-span-4`}>
            <div className='mt-6 flex items-center justify-center gap-4 rounded-full p-3' style={{ backgroundColor: navContainerBg }}>
              <span className='inline-flex h-11 w-11 items-center justify-center rounded-sm text-white' style={{ backgroundColor: activePrimary }}>
                <Home className='h-5 w-5' />
              </span>

              <span className='inline-flex h-11 w-11 items-center justify-center rounded-sm text-[#6E6D73]'>
                <Search className='h-5 w-5' />
              </span>

              <span className='inline-flex h-11 w-11 items-center justify-center rounded-sm text-[#6E6D73]'>
                <User className='h-5 w-5' />
              </span>
            </div>
          </div>

          <div className={`${panelClassName} md:col-span-3 xl:col-span-4`}>
            <p className='text-sm text-[#8B8A91]'>{labelText}</p>

            <p className='text-[108px] leading-none text-[#67666D]'>Aa</p>
          </div>

          <div className={`${panelClassName} md:col-span-1 xl:col-span-2`}>
            <div className='flex h-full items-center justify-center'>
              <span className='inline-flex h-14 w-14 items-center justify-center rounded-sm text-white' style={{ backgroundColor: activeTertiary }}>
                <Pencil className='h-6 w-6' />
              </span>
            </div>
          </div>

          <div className={`${panelClassName} md:col-span-2 xl:col-span-2`}>
            <div className='flex h-full items-center justify-center'>
              <span className='inline-flex items-center gap-2 rounded-sm px-4 py-2 text-[30px] md:text-sm' style={{ backgroundColor: '#CDD7EF', color: activePrimary }}>
                <Pencil className='h-4 w-4' />
                Label
              </span>
            </div>
          </div>

          <div className={`${panelClassName} md:col-span-3 xl:col-span-4`}>
            <div className='flex h-full items-center justify-center gap-2'>
              <span className='inline-flex h-10 w-10 items-center justify-center rounded-sm text-white' style={{ backgroundColor: activePrimary }}>
                <WandSparkles className='h-5 w-5' />
              </span>

              <span className='inline-flex h-10 w-10 items-center justify-center rounded-sm text-white' style={{ backgroundColor: activeNeutral }}>
                <Triangle className='h-5 w-5' />
              </span>

              <span className='inline-flex h-10 w-10 items-center justify-center rounded-sm text-white' style={{ backgroundColor: activeTertiary }}>
                <Tag className='h-5 w-5' />
              </span>

              <span className='inline-flex h-10 w-10 items-center justify-center rounded-sm bg-[#8F3E4C] text-white'>
                <Trash2 className='h-5 w-5' />
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className='mt-3 hidden text-[11px] text-[#8C8B92] md:block'>
        Primary {primaryColor} • Secondary {secondaryColor} • Tertiary {tertiaryColor} • Neutral {neutralColor}
      </div>
    </section>
  )
}
