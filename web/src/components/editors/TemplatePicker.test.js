import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import TemplatePicker from './TemplatePicker.vue'

describe('TemplatePicker', () => {
  it('previews threshold while sliding and commits it on change', async () => {
    const wrapper = mount(TemplatePicker, {
      props: { modelValue: [{ file: 'target.png', threshold: 0.8 }] },
    })
    const slider = wrapper.find('input[type="range"]')

    slider.element.value = '0.63'
    await slider.trigger('input')

    expect(wrapper.text()).toContain('0.63')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()

    await slider.trigger('change')
    expect(wrapper.emitted('update:modelValue')[0][0][0].threshold).toBe(0.63)
  })
})
