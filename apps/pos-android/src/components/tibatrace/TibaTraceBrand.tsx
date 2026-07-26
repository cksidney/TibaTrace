import { fontSize, spacing, text } from '@dawatrace/shared/design-system/index.js';
import { Image, StyleSheet, Text, View } from 'react-native';

const tibatraceLogo = require('../../assets/tibatrace-logo.jpeg');

export function TibaTraceBrand() {
  return (
    <View accessibilityRole="image" accessibilityLabel="TibaTrace — Trace. Trust. Health." style={styles.root}>
      <View style={styles.mark}>
        <Image source={tibatraceLogo} accessible={false} style={styles.logo} />
      </View>
      <View>
        <Text style={styles.name}>TibaTrace</Text>
        <Text style={styles.tagline}>Trace. Trust. Health.</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  mark: {
    width: 40,
    height: 40,
    overflow: 'hidden',
    borderRadius: 10,
    backgroundColor: '#fff',
  },
  logo: { width: 100, height: 100, transform: [{ translateX: -29 }, { translateY: -15 }] },
  name: { fontSize: fontSize.bodyLarge, fontWeight: '700', color: text.primary },
  tagline: { marginTop: 1, fontSize: fontSize.meta, color: text.secondary },
});
